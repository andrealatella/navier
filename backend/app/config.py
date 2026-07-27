"""Application settings, loaded from environment / .env."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Typed settings. Field names map to UPPER_CASE env vars (case-insensitive)."""

    model_config = SettingsConfigDict(
        env_file=(REPO_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    host: str = "0.0.0.0"
    port: int = 5700
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    uvicorn_reload: bool = True

    gemini_api_key: str = ""
    gemini_model_chat: str = "gemini-3.1-flash-lite"
    gemini_model_ticker: str = "gemini-3.1-flash-lite"
    enable_copilot: bool = True
    copilot_proactive: bool = False
    copilot_min_interval_s: int = 90
    copilot_daily_limit: int = 300
    copilot_temperature: float = 0.4
    copilot_max_tokens: int = 512
    copilot_timeout_s: float = 20.0

    enable_tts: bool = True
    tts_voice: str = ""
    tts_rate: int = 0
    tts_cache_dir: str = str(REPO_ROOT / "data" / "tts_cache")
    tts_output_device: str = ""

    enable_stt: bool = True
    stt_record_max_s: float = 12.0
    stt_silence_s: float = 1.0
    stt_listen_timeout_s: float = 5.0
    stt_beep_freq: int = 880
    stt_beep_ms: int = 150

    ors_api_key: str = ""
    google_maps_api_key: str = ""
    osrm_base_url: str = "https://router.project-osrm.org"
    ors_base_url: str = "https://api.openrouteservice.org"
    route_timeout_s: float = 20.0
    intercept_horizon_min: float = 30.0
    intercept_offset_km: float = 8.0
    intercept_min_core_km: float = 5.0
    intercept_snap_max_km: float = 3.0
    intercept_margin_min: float = 5.0
    view_step_km: float = 0.5
    view_standoff_km: float = 4.0
    view_rain_mmh: float = 2.0

    gpsd_host: str = "127.0.0.1"
    gpsd_port: int = 2947

    outlook_refresh_s: float = 43200.0
    outlook_retry_s: float = 3600.0

    dpc_allerte_refresh_s: float = 10800.0
    dpc_allerte_retry_s: float = 1800.0

    enable_dpc_products: bool = True
    dpc_products_stale_s: float = 900.0
    sri_sample_radius_km: float = 5.0

    enable_blitzortung: bool = True
    enable_dpc_radar: bool = True
    enable_openmeteo: bool = True
    enable_rainviewer: bool = True
    enable_pretemp: bool = True
    enable_dpc_allerte: bool = True
    enable_gpsd: bool = False
    enable_fake_lightning: bool = False

    enable_recorder: bool = True
    recorder_autostart: bool = False
    sessions_dir: str = str(REPO_ROOT / "data" / "sessions")
    replay_file: str = ""
    replay_speed: float = 1.0

    dpc_api_base: str = "https://radar-api.protezionecivile.it"
    radar_product: str = "VMI"
    radar_poll_s: float = 60.0
    radar_history_frames: int = 18
    radar_stale_s: float = 1200.0

    openmeteo_base_url: str = "https://api.open-meteo.com/v1/forecast"
    openmeteo_model: str = "italia_meteo_arpae_icon_2i"
    meteo_refresh_s: float = 3600.0
    meteo_retry_s: float = 300.0
    meteo_grid_step_deg: float = 1.0
    meteo_grid_chunk: int = 250
    meteo_chunk_delay_s: float = 12.0
    meteo_forecast_days: int = 1

    basemap_pmtiles: str = str(REPO_ROOT / "data" / "basemap.pmtiles")

    rainviewer_maps_url: str = "https://api.rainviewer.com/public/weather-maps.json"
    rainviewer_poll_s: float = 150.0
    rainviewer_color_scheme: int = 2
    rainviewer_smooth: int = 1
    rainviewer_snow: int = 1

    http_user_agent: str = "NAVIER/0.1 (storm chasing nowcasting, Italia)"

    dbz_core: float = 45.0
    dbz_envelope: float = 35.0
    min_area_km2: float = 20.0
    track_gate_kmh: float = 140.0
    track_max_misses: int = 2
    track_motion_frames: int = 4
    cone_halfangle_30_deg: float = 20.0
    cone_halfangle_60_deg: float = 30.0
    poly_simplify_deg: float = 0.01

    sev_w_dbz: float = 35.0
    sev_w_lightning: float = 25.0
    sev_w_area: float = 15.0
    sev_w_trend: float = 15.0
    sev_w_cape: float = 10.0
    sev_dbz_lo: float = 40.0
    sev_dbz_hi: float = 65.0
    sev_lightning_hi: float = 60.0
    sev_area_lo: float = 20.0
    sev_area_hi: float = 400.0
    sev_cape_lo: float = 500.0
    sev_cape_hi: float = 3000.0

    supercell_min_life_s: float = 2700.0
    supercell_dbz_min: float = 55.0
    supercell_dbz_window_s: float = 1200.0
    supercell_lightning_min: float = 15.0
    supercell_deviation_deg: float = 25.0
    supercell_min_speed_kmh: float = 15.0
    supercell_min_flow_ms: float = 5.0

    lightning_cluster_eps_deg: float = 0.07
    lightning_cluster_min_samples: int = 6
    lightning_cluster_window_s: float = 600.0
    jump_min_rate: float = 10.0
    jump_factor: float = 2.0

    alert_cooldown_s: float = 180.0
    alert_zone_km: float = 20.0
    lightning_near_km: float = 5.0
    lightning_near_off_km: float = 8.0
    lightning_near_window_s: float = 120.0
    cell_inbound_sev: int = 50
    cell_inbound_off_sev: int = 40
    cell_inbound_eta_min: float = 15.0
    hail_dbz_p2: float = 55.0
    hail_dbz_p1: float = 60.0
    hail_range_km: float = 30.0
    hail_cape_min: float = 1500.0
    hail_poh_min: float = 0.6
    flash_flood_sri_mmh: float = 30.0
    lightning_jump_range_km: float = 50.0
    new_strong_sev: int = 60
    new_strong_km: float = 80.0
    weakening_drop_pct: float = 0.30
    data_stale_radar_s: float = 900.0
    data_stale_lightning_s: float = 180.0

    processing_tick_s: float = 10.0

    italy_bbox_w: float = 5.5
    italy_bbox_e: float = 20.5
    italy_bbox_s: float = 35.0
    italy_bbox_n: float = 48.5

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def static_dir(self) -> Path:
        """Where the built frontend is served from (populated by `build` script)."""
        return Path(__file__).resolve().parent / "static_dist"

    @property
    def copilot_state_path(self) -> Path:
        """Persisted daily-call counter for the co-pilot budget."""
        return REPO_ROOT / "data" / "copilot_budget.json"

    @property
    def sessions_path(self) -> Path:
        """Where live sessions are recorded for replay."""
        return Path(self.sessions_dir)

    @property
    def basemap_pmtiles_path(self) -> Path:
        """Optional offline basemap archive; served with range support if present."""
        return Path(self.basemap_pmtiles)

    @property
    def tts_cache_path(self) -> Path:
        return Path(self.tts_cache_dir)


@lru_cache
def get_settings() -> Settings:
    """Cached settings singleton."""
    return Settings()


settings = get_settings()
