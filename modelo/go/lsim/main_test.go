package main

import (
	"math"
	"testing"
)

func mundo(n int) entrada {
	eq := make([]equipo, n)
	var ps []partido
	for i := 0; i < n; i++ {
		for j := 0; j < n; j++ {
			if i != j {
				ps = append(ps, partido{H: i, A: j, Lh: 1.4, La: 1.1})
			}
		}
	}
	return entrada{Equipos: eq, Partidos: ps, NSim: 4000, Semilla: 5, Desempates: []string{"puntos", "diferencia_goles", "goles_favor"}, Paso: 0.05}
}

func TestLasPosicionesSumanUnoPorEquipoYPorPosicion(t *testing.T) {
	r := simular(mundo(6))
	for i := range r.Conteo {
		s := 0
		for _, c := range r.Conteo[i] {
			s += c
		}
		if s != r.Utiles {
			t.Fatalf("equipo %d suma %d, esperaba %d", i, s, r.Utiles)
		}
	}
	for pos := 0; pos < 6; pos++ {
		s := 0
		for i := range r.Conteo {
			s += r.Conteo[i][pos]
		}
		if s != r.Utiles {
			t.Fatalf("posición %d suma %d", pos, s)
		}
	}
}

func TestEsReproducibleConLaMismaSemilla(t *testing.T) {
	a, b := simular(mundo(5)), simular(mundo(5))
	for i := range a.Conteo {
		for j := range a.Conteo[i] {
			if a.Conteo[i][j] != b.Conteo[i][j] {
				t.Fatal("no reproducible")
			}
		}
	}
}

func TestEquiposIgualesTienenPuntosMediosIguales(t *testing.T) {
	r := simular(mundo(6))
	var medias []float64
	for _, h := range r.Puntos {
		s, n := 0.0, 0
		for k, c := range h.Conta {
			s += float64(k * c)
			n += c
		}
		medias = append(medias, s/float64(n))
	}
	for _, m := range medias {
		if math.Abs(m-medias[0]) > 1.5 {
			t.Fatalf("las medias deberían ser parecidas: %v", medias)
		}
	}
}

func TestUnResultadoFijoSeRespeta(t *testing.T) {
	in := mundo(4)
	in.Partidos = []partido{{H: 0, A: 1, Lh: 1.4, La: 1.1, Fijo: &[2]int{5, 0}}}
	in.NSim = 100
	r := simular(in)
	if r.Puntos[0].Conta[3] != 100 || r.Puntos[1].Conta[0] != 100 {
		t.Fatal("el 5-0 fijo debía dar 3 puntos al local y 0 al visitante en todas las simulaciones")
	}
}
