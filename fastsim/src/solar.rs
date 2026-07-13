//! Port of scripts/solar_model.py — NOAA sun position, Haurwitz clear-sky,
//! DEM horizon shading, Erbs-style diffuse split, pyramid mounting, canopy.
//! Formula-for-formula identical to the Python (same constants).

const DEG: f64 = std::f64::consts::PI / 180.0;

/// (elevation_deg, azimuth_deg) — NOAA approximation
pub fn solar_position(lat_deg: f64, lon_deg: f64, day_of_year: u32, sec_of_day: f64) -> (f64, f64) {
    let hour = sec_of_day / 3600.0;
    let frac_year =
        2.0 * std::f64::consts::PI / 365.0 * (day_of_year as f64 - 1.0 + (hour - 12.0) / 24.0);
    let decl = 0.006918 - 0.399912 * frac_year.cos() + 0.070257 * frac_year.sin()
        - 0.006758 * (2.0 * frac_year).cos()
        + 0.000907 * (2.0 * frac_year).sin()
        - 0.002697 * (3.0 * frac_year).cos()
        + 0.00148 * (3.0 * frac_year).sin();
    let eqtime_min = 229.18
        * (0.000075 + 0.001868 * frac_year.cos()
            - 0.032077 * frac_year.sin()
            - 0.014615 * (2.0 * frac_year).cos()
            - 0.040849 * (2.0 * frac_year).sin());
    let tst_min = hour * 60.0 + eqtime_min + 4.0 * lon_deg;
    let ha = (tst_min / 4.0 - 180.0) * DEG;
    let lat = lat_deg * DEG;
    let cos_z = (lat.sin() * decl.sin() + lat.cos() * decl.cos() * ha.cos()).clamp(-1.0, 1.0);
    let elev = 90.0 - cos_z.acos() / DEG;
    let az = (-ha.sin()).atan2(decl.tan() * lat.cos() - lat.sin() * ha.cos()) / DEG;
    (elev, az.rem_euclid(360.0))
}

pub fn clear_sky_ghi(elev_deg: f64) -> f64 {
    if elev_deg <= 0.0 {
        return 0.0;
    }
    let cos_z = ((90.0 - elev_deg) * DEG).cos();
    1098.0 * cos_z * (-0.057 / cos_z).exp()
}

pub fn diffuse_fraction(kt: f64) -> f64 {
    (1.02 - 1.1 * kt).clamp(0.15, 0.98)
}

pub struct SiteSolar {
    pub pyramid: bool,
    pub tilt_deg: f64,
    pub canopy_tau: f64,
}

/// Instantaneous panel watts (panel_w × system_eff applied by caller config).
#[allow(clippy::too_many_arguments)]
pub fn solar_power_w(
    lat: f64,
    lon: f64,
    day_of_year: u32,
    sec_of_day: f64,
    kt: f64,
    horizon_deg: &[f64],
    site: &SiteSolar,
    panel_w: f64,
    system_eff: f64,
) -> f64 {
    let (elev, az) = solar_position(lat, lon, day_of_year, sec_of_day);
    let ghi = clear_sky_ghi(elev) * kt;
    if ghi <= 0.0 {
        return 0.0;
    }
    let fd = diffuse_fraction(kt);
    let mut diffuse_h = ghi * fd;
    let mut direct_h = ghi - diffuse_h;
    let n = horizon_deg.len();
    let idx = ((az / 360.0 * n as f64).round() as usize) % n;
    if elev < horizon_deg[idx] {
        direct_h = 0.0;
    }
    direct_h *= site.canopy_tau;
    diffuse_h *= site.canopy_tau;
    let plane = if site.pyramid {
        let beta = site.tilt_deg * DEG;
        let sin_e = (elev.max(5.0) * DEG).sin();
        let dni = direct_h / sin_e;
        let mut p = 0.0;
        for face_az in [0.0f64, 90.0, 180.0, 270.0] {
            let cos_inc = (elev * DEG).sin() * beta.cos()
                + (elev * DEG).cos() * beta.sin() * ((az - face_az) * DEG).cos();
            p += 0.25 * (dni * cos_inc.max(0.0) + diffuse_h * (1.0 + beta.cos()) / 2.0);
        }
        p
    } else {
        direct_h + diffuse_h
    };
    panel_w * (plane / 1000.0) * system_eff
}
