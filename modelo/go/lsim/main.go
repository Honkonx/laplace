// lsim — núcleo Monte Carlo del simulador de temporadas de Laplace (MM-41).
//
// Lee por stdin un JSON con la tabla, los partidos pendientes (con sus lambdas) y los parámetros, y escribe por stdout las posiciones y los puntos finales
// de cada equipo. Es la misma matemática que `backend/api/ml/laplace/liga.py::_nucleo` (Poisson independiente, incertidumbre de fuerza por equipo en pasos
// de `paso` en log, desempates configurables y sorteo final), con otro generador de números aleatorios: por eso los resultados son estadísticamente
// equivalentes, no idénticos bit a bit. Python sigue siendo la referencia y el respaldo.
package main

import (
	"bufio"
	"encoding/json"
	"fmt"
	"math"
	"math/rand/v2"
	"os"
	"sort"
)

type equipo struct {
	Pts int `json:"pts"`
	Gf  int `json:"gf"`
	Gc  int `json:"gc"`
}

type partido struct {
	H     int     `json:"h"`
	A     int     `json:"a"`
	Lh    float64 `json:"lh"`
	La    float64 `json:"la"`
	Fijo  *[2]int `json:"fijo"`
}

type entrada struct {
	Equipos    []equipo  `json:"equipos"`
	Partidos   []partido `json:"partidos"`
	NSim       int       `json:"n_sim"`
	Semilla    uint64    `json:"semilla"`
	Desempates []string  `json:"desempates"`
	Sigma      float64   `json:"sigma"`
	Paso       float64   `json:"paso"`
}

type histograma struct {
	Min   int   `json:"min"`
	Conta []int `json:"conta"`
}

type salida struct {
	Conteo [][]int      `json:"conteo"`
	Puntos []histograma `json:"puntos"`
	Utiles int          `json:"utiles"`
	Motor  string       `json:"motor"`
}

const lambdaMax = 10.0

func cdfPoisson(lam float64) []float64 {
	p := math.Exp(-lam)
	acum := p
	cdf := []float64{p}
	for k := 1; acum < 1-1e-13 && k <= 80; k++ {
		p *= lam / float64(k)
		acum += p
		cdf = append(cdf, acum)
	}
	cdf[len(cdf)-1] = 1.0
	return cdf
}

func muestra(cdf []float64, u float64) int {
	return sort.Search(len(cdf), func(i int) bool { return cdf[i] > u })
}

func simular(in entrada) salida {
	n := len(in.Equipos)
	conteo := make([][]int, n)
	for i := range conteo {
		conteo[i] = make([]int, n)
	}
	// puntos finales posibles: de min(pts) a max(pts)+3*partidos del equipo
	maxExtra := make([]int, n)
	for _, p := range in.Partidos {
		maxExtra[p.H] += 3
		maxExtra[p.A] += 3
	}
	hist := make([][]int, n)
	for i := range hist {
		hist[i] = make([]int, in.Equipos[i].Pts+maxExtra[i]+1-in.Equipos[i].Pts)
	}
	cdfBase := make([][2][]float64, len(in.Partidos))
	for k, p := range in.Partidos {
		cdfBase[k] = [2][]float64{cdfPoisson(p.Lh), cdfPoisson(p.La)}
	}
	paso := in.Paso
	if paso <= 0 {
		paso = 0.05
	}
	const dmax = 12
	cacheFuerza := make([][2*dmax + 1][2][]float64, len(in.Partidos))
	rnd := rand.New(rand.NewPCG(in.Semilla, 0x9e3779b97f4a7c15))
	rndF := rand.New(rand.NewPCG(in.Semilla+7919, 0x9e3779b97f4a7c15))
	pts := make([]int, n)
	gf := make([]int, n)
	gc := make([]int, n)
	niveles := make([]int, n)
	sorteo := make([]float64, n)
	orden := make([]int, n)
	utiles := 0
	for s := 0; s < in.NSim; s++ {
		for i, e := range in.Equipos {
			pts[i], gf[i], gc[i] = e.Pts, e.Gf, e.Gc
		}
		if in.Sigma > 0 {
			for i := range niveles {
				niveles[i] = int(math.Round(rndF.NormFloat64() * in.Sigma / paso))
			}
		}
		for k, p := range in.Partidos {
			ch, ca := cdfBase[k][0], cdfBase[k][1]
			if in.Sigma > 0 {
				d := niveles[p.H] - niveles[p.A]
				if d > dmax {
					d = dmax
				} else if d < -dmax {
					d = -dmax
				}
				c := &cacheFuerza[k][d+dmax]
				if c[0] == nil {
					f := math.Exp(paso * float64(d))
					c[0] = cdfPoisson(math.Min(p.Lh*f, lambdaMax*0.999))
					c[1] = cdfPoisson(math.Min(p.La/f, lambdaMax*0.999))
				}
				ch, ca = c[0], c[1]
			}
			a := muestra(ch, rnd.Float64())
			b := muestra(ca, rnd.Float64())
			if p.Fijo != nil {
				a, b = p.Fijo[0], p.Fijo[1]
			}
			gf[p.H] += a
			gc[p.H] += b
			gf[p.A] += b
			gc[p.A] += a
			switch {
			case a > b:
				pts[p.H] += 3
			case a < b:
				pts[p.A] += 3
			default:
				pts[p.H]++
				pts[p.A]++
			}
		}
		for i := range sorteo {
			sorteo[i] = rnd.Float64()
			orden[i] = i
		}
		sort.Slice(orden, func(x, y int) bool {
			i, j := orden[x], orden[y]
			for _, d := range in.Desempates {
				var vi, vj int
				switch d {
				case "puntos":
					vi, vj = pts[i], pts[j]
				case "diferencia_goles":
					vi, vj = gf[i]-gc[i], gf[j]-gc[j]
				case "goles_favor":
					vi, vj = gf[i], gf[j]
				}
				if vi != vj {
					return vi > vj
				}
			}
			return sorteo[i] < sorteo[j]
		})
		utiles++
		for pos, i := range orden {
			conteo[i][pos]++
			hist[i][pts[i]-in.Equipos[i].Pts]++
		}
	}
	puntos := make([]histograma, n)
	for i := range puntos {
		puntos[i] = histograma{Min: in.Equipos[i].Pts, Conta: hist[i]}
	}
	return salida{Conteo: conteo, Puntos: puntos, Utiles: utiles, Motor: "go"}
}

func main() {
	var in entrada
	if err := json.NewDecoder(bufio.NewReader(os.Stdin)).Decode(&in); err != nil {
		fmt.Fprintln(os.Stderr, "entrada inválida:", err)
		os.Exit(2)
	}
	if in.NSim <= 0 || len(in.Equipos) == 0 {
		fmt.Fprintln(os.Stderr, "n_sim y equipos deben ser positivos")
		os.Exit(2)
	}
	for _, p := range in.Partidos {
		if p.H < 0 || p.H >= len(in.Equipos) || p.A < 0 || p.A >= len(in.Equipos) || !(p.Lh > 0 && p.Lh < lambdaMax) || !(p.La > 0 && p.La < lambdaMax) {
			fmt.Fprintln(os.Stderr, "partido fuera de rango")
			os.Exit(2)
		}
	}
	if err := json.NewEncoder(os.Stdout).Encode(simular(in)); err != nil {
		os.Exit(1)
	}
}
