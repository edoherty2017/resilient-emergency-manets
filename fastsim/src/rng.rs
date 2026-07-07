//! SplitMix64 RNG + normal sampling. Statistically equivalent to (not
//! bit-compatible with) numpy's Generator — fastsim results match the Python
//! sim in distribution, which is what multi-seed sweeps consume.

pub struct Rng {
    state: u64,
    spare_normal: Option<f64>,
}

impl Rng {
    pub fn new(seed: u64) -> Self {
        Rng { state: seed.wrapping_add(0x9E3779B97F4A7C15), spare_normal: None }
    }

    #[inline]
    pub fn next_u64(&mut self) -> u64 {
        self.state = self.state.wrapping_add(0x9E3779B97F4A7C15);
        let mut z = self.state;
        z = (z ^ (z >> 30)).wrapping_mul(0xBF58476D1CE4E5B9);
        z = (z ^ (z >> 27)).wrapping_mul(0x94D049BB133111EB);
        z ^ (z >> 31)
    }

    /// Uniform in [0, 1)
    #[inline]
    pub fn f64(&mut self) -> f64 {
        (self.next_u64() >> 11) as f64 * (1.0 / (1u64 << 53) as f64)
    }

    #[inline]
    pub fn uniform(&mut self, lo: f64, hi: f64) -> f64 {
        lo + (hi - lo) * self.f64()
    }

    #[inline]
    pub fn below(&mut self, n: usize) -> usize {
        (self.f64() * n as f64) as usize % n.max(1)
    }

    /// Standard normal (Box-Muller, cached spare)
    pub fn normal(&mut self) -> f64 {
        if let Some(s) = self.spare_normal.take() {
            return s;
        }
        loop {
            let u = self.f64();
            if u <= f64::EPSILON {
                continue;
            }
            let v = self.f64();
            let r = (-2.0 * u.ln()).sqrt();
            let a = 2.0 * std::f64::consts::PI * v;
            self.spare_normal = Some(r * a.sin());
            return r * a.cos();
        }
    }

    /// Beta(a, b) via Jöhnk/gamma-free method for a,b < 1 fallback: use
    /// two-gamma with Marsaglia-Tsang for shape >= 1 (shifted for < 1).
    pub fn gamma(&mut self, shape: f64) -> f64 {
        if shape < 1.0 {
            let u = self.f64().max(f64::EPSILON);
            return self.gamma(shape + 1.0) * u.powf(1.0 / shape);
        }
        let d = shape - 1.0 / 3.0;
        let c = 1.0 / (9.0 * d).sqrt();
        loop {
            let x = self.normal();
            let v = (1.0 + c * x).powi(3);
            if v <= 0.0 {
                continue;
            }
            let u = self.f64();
            if u < 1.0 - 0.0331 * x.powi(4)
                || u.ln() < 0.5 * x * x + d * (1.0 - v + v.ln())
            {
                return d * v;
            }
        }
    }

    pub fn beta(&mut self, a: f64, b: f64) -> f64 {
        let x = self.gamma(a);
        let y = self.gamma(b);
        x / (x + y)
    }
}
