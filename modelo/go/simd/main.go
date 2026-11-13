// simd — microservicio local en Go que sirve el simulador de temporadas de Laplace.
//
// Reparto de lenguajes: Rust hace el cálculo caliente (modelo/rust/lsim), Python la lógica y Go la conexión y el servicio. Este servicio recibe el mismo JSON que el núcleo, lo pasa por
// stdin al binario nativo y devuelve su salida. Lo que aporta frente a lanzar el proceso desde Python:
//   - tope de simulaciones simultáneas (la que sobra recibe 503 con Retry-After, sin encolar);
//   - plazo real: al vencer, o si quien llamó se desconecta, el proceso del cálculo se MATA (un hilo de Python no se puede detener);
//   - solo escucha en la interfaz local: no es una API pública.
//
// Variables: LAPLACE_SIMD_ADDR (127.0.0.1:9200), LAPLACE_SIMD_NUCLEO (ruta del binario), LAPLACE_SIMD_MAX (2), LAPLACE_SIMD_PLAZO (segundos, 20).
package main

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"os"
	"os/exec"
	"strconv"
	"sync/atomic"
	"time"
)

const maxEntrada = 4 << 20
const maxSalida = 8 << 20

type servicio struct {
	nucleo   string
	cupo     chan struct{}
	plazo    time.Duration
	enCurso  atomic.Int64
	ejecutar func(ctx context.Context, entrada []byte) ([]byte, error)
}

func nuevo(nucleo string, max int, plazo time.Duration) *servicio {
	s := &servicio{nucleo: nucleo, cupo: make(chan struct{}, max), plazo: plazo}
	s.ejecutar = s.ejecutarNucleo
	return s
}

// ejecutarNucleo corre el binario nativo; exec.CommandContext lo mata si el contexto vence o se cancela.
func (s *servicio) ejecutarNucleo(ctx context.Context, entrada []byte) ([]byte, error) {
	cmd := exec.CommandContext(ctx, s.nucleo)
	cmd.Stdin = bytes.NewReader(entrada)
	var out, errb bytes.Buffer
	cmd.Stdout = &limitado{w: &out, max: maxSalida}
	cmd.Stderr = &errb
	if err := cmd.Run(); err != nil {
		if ctx.Err() != nil {
			return nil, ctx.Err()
		}
		return nil, fmt.Errorf("el núcleo terminó con error: %w (%s)", err, bytes.TrimSpace(errb.Bytes()))
	}
	return out.Bytes(), nil
}

type limitado struct {
	w   *bytes.Buffer
	max int
}

func (l *limitado) Write(p []byte) (int, error) {
	if l.w.Len()+len(p) > l.max {
		return 0, errors.New("salida demasiado grande")
	}
	return l.w.Write(p)
}

func (s *servicio) manejador() http.Handler {
	mux := http.NewServeMux()
	salud := func(w http.ResponseWriter, r *http.Request) {
		escribirJSON(w, 200, map[string]any{"ok": true, "servicio": "simd", "max": cap(s.cupo), "en_curso": s.enCurso.Load()})
	}
	mux.HandleFunc("GET /salud", salud)
	mux.HandleFunc("GET /health", salud) // el control de arranque (`laplace`) pregunta por /health a todos los servicios
	mux.HandleFunc("POST /v1/simular", func(w http.ResponseWriter, r *http.Request) {
		select {
		case s.cupo <- struct{}{}:
			defer func() { <-s.cupo }()
		default:
			w.Header().Set("Retry-After", "10")
			escribirJSON(w, 503, map[string]any{"error": "hay simulaciones en curso; inténtalo en unos segundos"})
			return
		}
		s.enCurso.Add(1)
		defer s.enCurso.Add(-1)
		entrada, err := io.ReadAll(http.MaxBytesReader(w, r.Body, maxEntrada))
		if err != nil || !json.Valid(entrada) {
			escribirJSON(w, 400, map[string]any{"error": "entrada inválida o demasiado grande"})
			return
		}
		ctx, cancelar := context.WithTimeout(r.Context(), s.plazo) // el plazo y la desconexión de quien llama matan el proceso
		defer cancelar()
		salida, err := s.ejecutar(ctx, entrada)
		switch {
		case errors.Is(err, context.DeadlineExceeded):
			escribirJSON(w, 504, map[string]any{"error": "la simulación tardó demasiado y se canceló"})
		case errors.Is(err, context.Canceled):
			// quien llamó se fue: no hay a quién responder
		case err != nil:
			escribirJSON(w, 502, map[string]any{"error": "falló el núcleo de cálculo"})
		default:
			w.Header().Set("Content-Type", "application/json")
			_, _ = w.Write(salida)
		}
	})
	return mux
}

func escribirJSON(w http.ResponseWriter, codigo int, cuerpo any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(codigo)
	_ = json.NewEncoder(w).Encode(cuerpo)
}

func entero(nombre string, defecto int) int {
	if v, err := strconv.Atoi(os.Getenv(nombre)); err == nil && v > 0 {
		return v
	}
	return defecto
}

func esLocal(direccion string) bool {
	host, _, err := net.SplitHostPort(direccion)
	if err != nil {
		return false
	}
	ip := net.ParseIP(host)
	return host == "localhost" || (ip != nil && ip.IsLoopback())
}

func main() {
	direccion := os.Getenv("LAPLACE_SIMD_ADDR")
	if direccion == "" {
		direccion = "127.0.0.1:9200"
	}
	if !esLocal(direccion) {
		fmt.Fprintln(os.Stderr, "simd solo escucha en la interfaz local (127.0.0.1 o ::1)")
		os.Exit(2)
	}
	nucleo := os.Getenv("LAPLACE_SIMD_NUCLEO")
	if nucleo == "" {
		fmt.Fprintln(os.Stderr, "falta LAPLACE_SIMD_NUCLEO (ruta del binario modelo/rust/bin/lsim)")
		os.Exit(2)
	}
	s := nuevo(nucleo, entero("LAPLACE_SIMD_MAX", 2), time.Duration(entero("LAPLACE_SIMD_PLAZO", 20))*time.Second)
	srv := &http.Server{Addr: direccion, Handler: s.manejador(), ReadHeaderTimeout: 5 * time.Second, ReadTimeout: 15 * time.Second, WriteTimeout: 40 * time.Second}
	fmt.Println("simd escuchando en", direccion)
	if err := srv.ListenAndServe(); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
