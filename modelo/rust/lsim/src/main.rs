// lsim (Rust) — núcleo Monte Carlo del simulador de temporadas de Laplace.
//
// Mismo protocolo que `modelo/go/lsim`: lee por stdin un JSON con la tabla, los partidos pendientes (con sus lambdas) y los parámetros, y escribe por stdout
// el conteo de posiciones y el histograma de puntos finales de cada equipo. Es la misma matemática que `backend/api/ml/laplace/liga.py::_nucleo` (Poisson
// independiente, incertidumbre de fuerza por equipo en pasos de `paso` en log, desempates configurables y sorteo final) con otro generador de números
// aleatorios (xoshiro256++): por eso es estadísticamente equivalente a Python y a Go, no idéntico bit a bit.
//
// Rendimiento: las simulaciones se reparten en BLOQUES FIJOS (`BLOQUES`), cada uno con su propio flujo aleatorio, y se procesan en paralelo. Como el reparto no
// depende del número de núcleos, la misma semilla da el mismo resultado en cualquier máquina.
use serde::{Deserialize, Serialize};
use std::io::Read;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Mutex;

const LAMBDA_MAX: f64 = 10.0;
const DMAX: i64 = 12;
const BLOQUES: usize = 16;

#[derive(Deserialize, Clone)]
struct Equipo {
    pts: i64,
    gf: i64,
    gc: i64,
}

#[derive(Deserialize, Clone)]
struct Partido {
    h: usize,
    a: usize,
    lh: f64,
    la: f64,
    #[serde(default)]
    fijo: Option<[i64; 2]>,
}

#[derive(Deserialize)]
struct Entrada {
    equipos: Vec<Equipo>,
    partidos: Vec<Partido>,
    n_sim: usize,
    semilla: u64,
    desempates: Vec<String>,
    sigma: f64,
    paso: f64,
}

#[derive(Serialize, PartialEq, Debug)]
struct Histograma {
    min: i64,
    conta: Vec<u64>,
}

#[derive(Serialize, PartialEq, Debug)]
struct Salida {
    conteo: Vec<Vec<u64>>,
    puntos: Vec<Histograma>,
    utiles: usize,
    motor: &'static str,
}

/// xoshiro256++ sembrado con splitmix64: rápido, de calidad estadística sobrada para Monte Carlo y sin dependencias.
struct Rng {
    s: [u64; 4],
}

fn splitmix64(x: &mut u64) -> u64 {
    *x = x.wrapping_add(0x9e37_79b9_7f4a_7c15);
    let mut z = *x;
    z = (z ^ (z >> 30)).wrapping_mul(0xbf58_476d_1ce4_e5b9);
    z = (z ^ (z >> 27)).wrapping_mul(0x94d0_49bb_1331_11eb);
    z ^ (z >> 31)
}

impl Rng {
    fn nuevo(semilla: u64) -> Self {
        let mut x = semilla;
        Rng { s: [splitmix64(&mut x), splitmix64(&mut x), splitmix64(&mut x), splitmix64(&mut x)] }
    }
    fn siguiente(&mut self) -> u64 {
        let r = self.s[0].wrapping_add(self.s[3]).rotate_left(23).wrapping_add(self.s[0]);
        let t = self.s[1] << 17;
        self.s[2] ^= self.s[0];
        self.s[3] ^= self.s[1];
        self.s[1] ^= self.s[2];
        self.s[0] ^= self.s[3];
        self.s[2] ^= t;
        self.s[3] = self.s[3].rotate_left(45);
        r
    }
    /// Uniforme en [0, 1) con 53 bits.
    fn uniforme(&mut self) -> f64 {
        (self.siguiente() >> 11) as f64 * (1.0 / (1u64 << 53) as f64)
    }
    /// Normal estándar por Box-Muller (u1 en (0, 1]).
    fn normal(&mut self) -> f64 {
        let u1 = 1.0 - self.uniforme();
        let u2 = self.uniforme();
        (-2.0 * u1.ln()).sqrt() * (std::f64::consts::TAU * u2).cos()
    }
}

fn cdf_poisson(lam: f64) -> Vec<f64> {
    let mut p = (-lam).exp();
    let mut acum = p;
    let mut cdf = vec![p];
    let mut k = 1u32;
    while acum < 1.0 - 1e-13 && k <= 80 {
        p *= lam / k as f64;
        acum += p;
        cdf.push(acum);
        k += 1;
    }
    let ultimo = cdf.len() - 1;
    cdf[ultimo] = 1.0;
    cdf
}

/// Primer índice con cdf[i] > u (búsqueda binaria, igual que `sort.Search` en Go y `bisect_right` en Python).
fn muestra(cdf: &[f64], u: f64) -> i64 {
    cdf.partition_point(|&x| x <= u) as i64
}

#[derive(Clone, Copy)]
enum Criterio {
    Puntos,
    DiferenciaGoles,
    GolesFavor,
}

struct Parcial {
    conteo: Vec<Vec<u64>>,
    hist: Vec<Vec<u64>>,
    utiles: usize,
}

type CdfPar = (Vec<f64>, Vec<f64>);

fn bloque(entrada: &Entrada, criterios: &[Criterio], base: &[CdfPar], paso: f64, desde: usize, hasta: usize, indice: usize) -> Parcial {
    let n = entrada.equipos.len();
    let mut conteo = vec![vec![0u64; n]; n];
    let mut max_extra = vec![0usize; n];
    for p in &entrada.partidos {
        max_extra[p.h] += 3;
        max_extra[p.a] += 3;
    }
    let mut hist: Vec<Vec<u64>> = (0..n).map(|i| vec![0u64; max_extra[i] + 1]).collect();
    // flujos propios del bloque: el principal (goles y sorteo) y el de la fuerza de cada equipo
    let mut rnd = Rng::nuevo(entrada.semilla ^ (indice as u64).wrapping_mul(0x9e37_79b9_7f4a_7c15));
    let mut rnd_f = Rng::nuevo(entrada.semilla.wrapping_add(7919) ^ (indice as u64).wrapping_mul(0xd1b5_4a32_d192_ed03));
    let mut cache: Vec<Vec<Option<CdfPar>>> = vec![vec![None; (2 * DMAX + 1) as usize]; entrada.partidos.len()];
    let mut pts = vec![0i64; n];
    let mut gf = vec![0i64; n];
    let mut gc = vec![0i64; n];
    let mut niveles = vec![0i64; n];
    let mut sorteo = vec![0f64; n];
    let mut orden: Vec<usize> = (0..n).collect();
    let mut utiles = 0usize;
    for _ in desde..hasta {
        for (i, e) in entrada.equipos.iter().enumerate() {
            pts[i] = e.pts;
            gf[i] = e.gf;
            gc[i] = e.gc;
        }
        if entrada.sigma > 0.0 {
            for nv in niveles.iter_mut() {
                *nv = (rnd_f.normal() * entrada.sigma / paso).round() as i64;
            }
        }
        for (k, p) in entrada.partidos.iter().enumerate() {
            let (ch, ca): (&[f64], &[f64]) = if entrada.sigma > 0.0 {
                let d = (niveles[p.h] - niveles[p.a]).clamp(-DMAX, DMAX);
                let celda = &mut cache[k][(d + DMAX) as usize];
                if celda.is_none() {
                    let f = (paso * d as f64).exp();
                    *celda = Some((cdf_poisson((p.lh * f).min(LAMBDA_MAX * 0.999)), cdf_poisson((p.la / f).min(LAMBDA_MAX * 0.999))));
                }
                let c = celda.as_ref().expect("recién calculada");
                (&c.0, &c.1)
            } else {
                (&base[k].0, &base[k].1)
            };
            let mut a = muestra(ch, rnd.uniforme());
            let mut b = muestra(ca, rnd.uniforme());
            if let Some(f) = p.fijo {
                a = f[0];
                b = f[1];
            }
            gf[p.h] += a;
            gc[p.h] += b;
            gf[p.a] += b;
            gc[p.a] += a;
            if a > b {
                pts[p.h] += 3;
            } else if a < b {
                pts[p.a] += 3;
            } else {
                pts[p.h] += 1;
                pts[p.a] += 1;
            }
        }
        for i in 0..n {
            sorteo[i] = rnd.uniforme();
            orden[i] = i;
        }
        // n es pequeño (una liga): la inserción gana a un ordenamiento general
        for x in 1..n {
            let actual = orden[x];
            let mut y = x;
            while y > 0 && delante(actual, orden[y - 1], criterios, &pts, &gf, &gc, &sorteo) {
                orden[y] = orden[y - 1];
                y -= 1;
            }
            orden[y] = actual;
        }
        utiles += 1;
        for (pos, &i) in orden.iter().enumerate() {
            conteo[i][pos] += 1;
            hist[i][(pts[i] - entrada.equipos[i].pts) as usize] += 1;
        }
    }
    Parcial { conteo, hist, utiles }
}

/// ¿`i` va delante de `j`? Los criterios en orden; si empatan en todos, decide el sorteo.
fn delante(i: usize, j: usize, criterios: &[Criterio], pts: &[i64], gf: &[i64], gc: &[i64], sorteo: &[f64]) -> bool {
    for c in criterios {
        let (vi, vj) = match c {
            Criterio::Puntos => (pts[i], pts[j]),
            Criterio::DiferenciaGoles => (gf[i] - gc[i], gf[j] - gc[j]),
            Criterio::GolesFavor => (gf[i], gf[j]),
        };
        if vi != vj {
            return vi > vj;
        }
    }
    sorteo[i] < sorteo[j]
}

fn simular(entrada: &Entrada, hilos: usize) -> Salida {
    let n = entrada.equipos.len();
    let paso = if entrada.paso > 0.0 { entrada.paso } else { 0.05 };
    let criterios: Vec<Criterio> = entrada
        .desempates
        .iter()
        .filter_map(|d| match d.as_str() {
            "puntos" => Some(Criterio::Puntos),
            "diferencia_goles" => Some(Criterio::DiferenciaGoles),
            "goles_favor" => Some(Criterio::GolesFavor),
            _ => None,
        })
        .collect();
    let base: Vec<CdfPar> = entrada.partidos.iter().map(|p| (cdf_poisson(p.lh), cdf_poisson(p.la))).collect();
    // reparto fijo en bloques: no depende del número de hilos
    let rangos: Vec<(usize, usize)> = (0..BLOQUES).map(|b| (b * entrada.n_sim / BLOQUES, (b + 1) * entrada.n_sim / BLOQUES)).collect();
    let siguiente = AtomicUsize::new(0);
    let resultados: Mutex<Vec<(usize, Parcial)>> = Mutex::new(Vec::with_capacity(BLOQUES));
    std::thread::scope(|s| {
        for _ in 0..hilos.max(1).min(BLOQUES) {
            s.spawn(|| loop {
                let b = siguiente.fetch_add(1, Ordering::Relaxed);
                if b >= BLOQUES {
                    break;
                }
                let (desde, hasta) = rangos[b];
                if hasta > desde {
                    let parcial = bloque(entrada, &criterios, &base, paso, desde, hasta, b);
                    resultados.lock().expect("sin pánico dentro del candado").push((b, parcial));
                }
            });
        }
    });
    let mut partes = resultados.into_inner().expect("sin pánico dentro del candado");
    partes.sort_by_key(|(b, _)| *b);
    let mut conteo = vec![vec![0u64; n]; n];
    let mut max_extra = vec![0usize; n];
    for p in &entrada.partidos {
        max_extra[p.h] += 3;
        max_extra[p.a] += 3;
    }
    let mut hist: Vec<Vec<u64>> = (0..n).map(|i| vec![0u64; max_extra[i] + 1]).collect();
    let mut utiles = 0usize;
    for (_, p) in &partes {
        utiles += p.utiles;
        for i in 0..n {
            for pos in 0..n {
                conteo[i][pos] += p.conteo[i][pos];
            }
            for (k, c) in p.hist[i].iter().enumerate() {
                hist[i][k] += c;
            }
        }
    }
    let puntos = (0..n).map(|i| Histograma { min: entrada.equipos[i].pts, conta: hist[i].clone() }).collect();
    Salida { conteo, puntos, utiles, motor: "rust" }
}

fn validar(e: &Entrada) -> Result<(), &'static str> {
    if e.n_sim == 0 || e.equipos.is_empty() {
        return Err("n_sim y equipos deben ser positivos");
    }
    let n = e.equipos.len();
    for p in &e.partidos {
        if p.h >= n || p.a >= n || !(p.lh > 0.0 && p.lh < LAMBDA_MAX) || !(p.la > 0.0 && p.la < LAMBDA_MAX) {
            return Err("partido fuera de rango");
        }
    }
    Ok(())
}

fn main() {
    let mut texto = String::new();
    if std::io::stdin().read_to_string(&mut texto).is_err() {
        eprintln!("no se pudo leer la entrada");
        std::process::exit(2);
    }
    let entrada: Entrada = match serde_json::from_str(&texto) {
        Ok(e) => e,
        Err(err) => {
            eprintln!("entrada inválida: {err}");
            std::process::exit(2);
        }
    };
    if let Err(m) = validar(&entrada) {
        eprintln!("{m}");
        std::process::exit(2);
    }
    let hilos = std::thread::available_parallelism().map(|n| n.get()).unwrap_or(1);
    match serde_json::to_writer(std::io::stdout().lock(), &simular(&entrada, hilos)) {
        Ok(()) => {}
        Err(_) => std::process::exit(1),
    }
}

#[cfg(test)]
mod pruebas {
    use super::*;

    fn entrada(equipos: Vec<(i64, i64, i64)>, partidos: Vec<Partido>, n_sim: usize, sigma: f64) -> Entrada {
        Entrada {
            equipos: equipos.into_iter().map(|(pts, gf, gc)| Equipo { pts, gf, gc }).collect(),
            partidos,
            n_sim,
            semilla: 42,
            desempates: vec!["puntos".into(), "diferencia_goles".into(), "goles_favor".into()],
            sigma,
            paso: 0.05,
        }
    }

    #[test]
    fn sin_partidos_pendientes_la_tabla_no_cambia() {
        let s = simular(&entrada(vec![(10, 5, 2), (7, 3, 3), (1, 0, 9)], vec![], 1000, 0.0), 2);
        assert_eq!(s.utiles, 1000);
        for (i, pos) in [(0usize, 0usize), (1, 1), (2, 2)] {
            assert_eq!(s.conteo[i][pos], 1000, "el equipo {i} siempre en la posición {pos}");
        }
    }

    #[test]
    fn un_resultado_fijado_se_respeta() {
        let p = Partido { h: 0, a: 1, lh: 1.0, la: 1.0, fijo: Some([3, 0]) };
        let s = simular(&entrada(vec![(0, 0, 0), (0, 0, 0)], vec![p], 500, 0.0), 1);
        assert_eq!(s.puntos[0].conta, vec![0, 0, 0, 500], "el local suma 3 puntos en todas");
        assert_eq!(s.puntos[1].conta, vec![500, 0, 0, 0]);
    }

    #[test]
    fn el_resultado_no_depende_del_numero_de_hilos() {
        let ps = vec![Partido { h: 0, a: 1, lh: 1.6, la: 1.1, fijo: None }, Partido { h: 1, a: 2, lh: 1.2, la: 1.2, fijo: None }, Partido { h: 2, a: 0, lh: 0.9, la: 1.8, fijo: None }];
        let e = entrada(vec![(3, 2, 2), (3, 2, 2), (3, 2, 2)], ps, 4000, 0.12);
        assert_eq!(simular(&e, 1), simular(&e, 8), "mismo reparto en bloques, mismo resultado");
    }

    #[test]
    fn dos_equipos_iguales_se_reparten_la_primera_posicion_a_partes_casi_iguales() {
        let ps = vec![Partido { h: 0, a: 1, lh: 1.3, la: 1.3, fijo: None }, Partido { h: 1, a: 0, lh: 1.3, la: 1.3, fijo: None }];
        let s = simular(&entrada(vec![(0, 0, 0), (0, 0, 0)], ps, 40_000, 0.0), 4);
        let p0 = s.conteo[0][0] as f64 / s.utiles as f64;
        assert!((p0 - 0.5).abs() < 0.02, "equipos simétricos: {p0}");
    }

    #[test]
    fn el_generador_es_uniforme_y_la_normal_tiene_media_cero() {
        let mut r = Rng::nuevo(7);
        let n = 200_000;
        let m: f64 = (0..n).map(|_| r.uniforme()).sum::<f64>() / n as f64;
        assert!((m - 0.5).abs() < 0.005, "media uniforme {m}");
        let z: Vec<f64> = (0..n).map(|_| r.normal()).collect();
        let mz = z.iter().sum::<f64>() / n as f64;
        let vz = z.iter().map(|x| (x - mz).powi(2)).sum::<f64>() / n as f64;
        assert!(mz.abs() < 0.01 && (vz - 1.0).abs() < 0.02, "normal: media {mz} varianza {vz}");
    }

    #[test]
    fn la_cdf_de_poisson_suma_uno_y_el_muestreo_respeta_los_extremos() {
        let c = cdf_poisson(2.0);
        assert_eq!(*c.last().unwrap(), 1.0);
        assert_eq!(muestra(&c, 0.0), 0);
        assert!(muestra(&c, 0.999_999) >= 5);
    }
}
