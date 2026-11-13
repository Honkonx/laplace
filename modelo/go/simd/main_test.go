package main

import (
	"context"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"
)

func peticion(s *servicio, cuerpo string) *httptest.ResponseRecorder {
	rr := httptest.NewRecorder()
	r := httptest.NewRequest("POST", "/v1/simular", strings.NewReader(cuerpo))
	s.manejador().ServeHTTP(rr, r)
	return rr
}

func TestSaludDiceCuantasSimulacionesCaben(t *testing.T) {
	s := nuevo("x", 2, time.Second)
	rr := httptest.NewRecorder()
	s.manejador().ServeHTTP(rr, httptest.NewRequest("GET", "/salud", nil))
	if rr.Code != 200 || !strings.Contains(rr.Body.String(), `"max":2`) {
		t.Fatalf("salud: %d %s", rr.Code, rr.Body.String())
	}
}

func TestEntradaInvalidaRecibe400(t *testing.T) {
	s := nuevo("x", 1, time.Second)
	s.ejecutar = func(ctx context.Context, e []byte) ([]byte, error) { t.Fatal("no debe ejecutarse"); return nil, nil }
	if rr := peticion(s, "no es json"); rr.Code != 400 {
		t.Fatalf("esperaba 400, obtuve %d", rr.Code)
	}
}

func TestLaSalidaDelNucleoSeDevuelveTalCual(t *testing.T) {
	s := nuevo("x", 1, time.Second)
	s.ejecutar = func(ctx context.Context, e []byte) ([]byte, error) { return []byte(`{"motor":"rust"}`), nil }
	rr := peticion(s, `{"n_sim":1}`)
	if rr.Code != 200 || rr.Body.String() != `{"motor":"rust"}` {
		t.Fatalf("%d %s", rr.Code, rr.Body.String())
	}
}

func TestElPlazoCancelaElCalculoYResponde504(t *testing.T) {
	s := nuevo("x", 1, 50*time.Millisecond)
	cancelado := make(chan bool, 1)
	s.ejecutar = func(ctx context.Context, e []byte) ([]byte, error) {
		<-ctx.Done() // el cálculo lento solo termina cuando le cancelan
		cancelado <- true
		return nil, ctx.Err()
	}
	if rr := peticion(s, `{"n_sim":1}`); rr.Code != http.StatusGatewayTimeout {
		t.Fatalf("esperaba 504, obtuve %d", rr.Code)
	}
	select {
	case <-cancelado:
	case <-time.After(time.Second):
		t.Fatal("el cálculo no se canceló")
	}
}

func TestConElCupoLlenoLaSiguienteRecibe503ConRetryAfterYElCupoVuelve(t *testing.T) {
	s := nuevo("x", 1, 2*time.Second)
	suelta := make(chan struct{})
	entro := make(chan struct{})
	s.ejecutar = func(ctx context.Context, e []byte) ([]byte, error) {
		close(entro)
		<-suelta
		return []byte(`{}`), nil
	}
	hecho := make(chan int, 1)
	go func() { hecho <- peticion(s, `{"n_sim":1}`).Code }()
	<-entro
	rr := peticion(s, `{"n_sim":1}`)
	if rr.Code != 503 || rr.Header().Get("Retry-After") == "" {
		t.Fatalf("esperaba 503 con Retry-After, obtuve %d", rr.Code)
	}
	close(suelta)
	if c := <-hecho; c != 200 {
		t.Fatalf("la primera debía terminar bien: %d", c)
	}
	s.ejecutar = func(ctx context.Context, e []byte) ([]byte, error) { return []byte(`{}`), nil }
	if rr := peticion(s, `{"n_sim":1}`); rr.Code != 200 {
		t.Fatalf("el cupo no volvió: %d", rr.Code)
	}
}

func TestSoloEscuchaEnLaInterfazLocal(t *testing.T) {
	for dir, esperado := range map[string]bool{"127.0.0.1:9200": true, "[::1]:9200": true, "localhost:9200": true, "0.0.0.0:9200": false, "203.0.113.5:9200": false, ":9200": false} {
		if esLocal(dir) != esperado {
			t.Errorf("%s: esperaba %v", dir, esperado)
		}
	}
}

type errTest string

func (e errTest) Error() string { return string(e) }

func TestUnFalloDelNucleoRecibe502SinFiltrarDetalles(t *testing.T) {
	s := nuevo("x", 1, time.Second)
	s.ejecutar = func(ctx context.Context, e []byte) ([]byte, error) { return nil, errTest("detalle interno: ruta secreta del equipo") }
	rr := peticion(s, `{"n_sim":1}`)
	if rr.Code != 502 || strings.Contains(rr.Body.String(), "ruta secreta") {
		t.Fatalf("%d %s", rr.Code, rr.Body.String())
	}
}
