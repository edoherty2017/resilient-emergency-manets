//! SplitMix64 RNG + normal sampling. This is intentionally not bit-compatible
//! with NumPy's Generator. Sharing nominal uniform/normal distributions does
//! not establish Python/Rust model parity; bounded metric differences must be
//! measured on matched multi-seed runs.

#[derive(Clone, Debug)]
pub struct Rng {
    state: u64,
    spare_normal: Option<f64>,
}

impl Rng {
    pub fn new(seed: u64) -> Self {
        Rng {
            state: seed.wrapping_add(0x9E3779B97F4A7C15),
            spare_normal: None,
        }
    }

    /// Build an independent, reproducible stream from a master seed and a
    /// stable numeric domain tag.  Simulation subsystems use separate streams
    /// so, for example, adding a MAC backoff draw cannot change SOS incidence.
    pub fn stream(master_seed: u64, domain: u64) -> Self {
        Self::new(Self::mix64(master_seed ^ Self::mix64(domain)))
    }

    /// Stateless SplitMix64 finalizer for deterministic keyed choices (CAD
    /// phase and order-independent reservoir priorities).
    pub fn mix64(mut z: u64) -> u64 {
        z = (z ^ (z >> 30)).wrapping_mul(0xBF58476D1CE4E5B9);
        z = (z ^ (z >> 27)).wrapping_mul(0x94D049BB133111EB);
        z ^ (z >> 31)
    }

    /// A deterministic uniform variate keyed by `(master_seed, domain, key)`;
    /// this does not consume any stateful stream.
    pub fn keyed_f64(master_seed: u64, domain: u64, key: u64) -> f64 {
        let bits = Self::mix64(master_seed ^ Self::mix64(domain) ^ Self::mix64(key));
        (bits >> 11) as f64 * (1.0 / (1u64 << 53) as f64)
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
}

#[cfg(test)]
mod tests {
    use super::Rng;

    #[test]
    fn streams_are_reproducible_and_isolated() {
        const TRAFFIC: u64 = 0x5452_4146_4649_4301;
        const MAC: u64 = 0x4d41_4300_0000_0002;
        let mut traffic_a = Rng::stream(42, TRAFFIC);
        let mut traffic_b = Rng::stream(42, TRAFFIC);
        let mut mac = Rng::stream(42, MAC);

        let first = traffic_a.next_u64();
        for _ in 0..10_000 {
            mac.next_u64();
        }
        assert_eq!(first, traffic_b.next_u64());
        assert_eq!(traffic_a.next_u64(), traffic_b.next_u64());
    }

    #[test]
    fn keyed_values_are_stable_and_domain_separated() {
        let a = Rng::keyed_f64(7, 11, 13);
        assert_eq!(a, Rng::keyed_f64(7, 11, 13));
        assert_ne!(a, Rng::keyed_f64(7, 12, 13));
        assert!((0.0..1.0).contains(&a));
    }
}
