#!/usr/bin/env python3
"""
Julius Health — Garmin sync script
Runs at 9am daily, pulls data from Garmin Connect, saves to GitHub
"""

import os
import json
import datetime
import traceback
from garminconnect import Garmin
from github import Github

# ── Credentials from environment variables ──────────────────────────────────
GARMIN_EMAIL    = os.environ.get("GARMIN_EMAIL")
GARMIN_PASSWORD = os.environ.get("GARMIN_PASSWORD")
GITHUB_TOKEN    = os.environ.get("GITHUB_TOKEN")
GITHUB_REPO     = os.environ.get("GITHUB_REPO", "juliuskvx/julius-health")

def safe_get(fn, default=None):
    try:
        return fn()
    except Exception:
        return default

def sync():
    today = datetime.date.today()
    yesterday = today - datetime.timedelta(days=1)
    date_str  = today.isoformat()
    yest_str  = yesterday.isoformat()

    print(f"[{date_str}] Connecting to Garmin Connect...")
    client = Garmin(GARMIN_EMAIL, GARMIN_PASSWORD)
    client.login()
    print("Connected.")

    # ── Sleep — pull TODAY (last night's sleep syncs under today's date) ──────
    sleep_raw  = safe_get(lambda: client.get_sleep_data(date_str), {})
    # fallback to yesterday if today has no data yet
    if not sleep_raw or not sleep_raw.get("dailySleepDTO", {}).get("sleepTimeSeconds"):
        sleep_raw = safe_get(lambda: client.get_sleep_data(yest_str), {})
    sleep_data = sleep_raw.get("dailySleepDTO", {}) if sleep_raw else {}

    # Sleep score: try multiple field paths Garmin uses
    sleep_score = (
        sleep_data.get("sleepScores", {}).get("overall", {}).get("value")
        or sleep_data.get("sleepScore")
        or sleep_data.get("averageSleepScore")
    )

    sleep = {
        "date":             date_str,
        "score":            sleep_score,
        "duration_seconds": sleep_data.get("sleepTimeSeconds"),
        "deep_seconds":     sleep_data.get("deepSleepSeconds"),
        "light_seconds":    sleep_data.get("lightSleepSeconds"),
        "rem_seconds":      sleep_data.get("remSleepSeconds"),
        "awake_seconds":    sleep_data.get("awakeSleepSeconds"),
        "stages":           sleep_data.get("sleepLevels") or [],
    }

    # ── HRV — pull TODAY ──────────────────────────────────────────────────────
    hrv_raw = safe_get(lambda: client.get_hrv_data(date_str), {})
    if not hrv_raw:
        hrv_raw = safe_get(lambda: client.get_hrv_data(yest_str), {})
    hrv_summary = hrv_raw.get("hrvSummary", {}) if hrv_raw else {}
    hrv = {
        "weekly_avg":      hrv_summary.get("weeklyAvg"),
        "last_night":      hrv_summary.get("lastNight"),
        "last_night_5min": hrv_summary.get("lastNight5MinHigh"),
        "status":          hrv_summary.get("status"),
    }

    # ── Body Battery — most recent non-null value ─────────────────────────────
    bb_raw = safe_get(lambda: client.get_body_battery(date_str), [])
    bb_values = []
    if isinstance(bb_raw, list):
        for item in bb_raw:
            if isinstance(item, dict) and "bodyBatteryValuesArray" in item:
                bb_values = item["bodyBatteryValuesArray"]
                break
    # Get most recent non-null value (not first — that's midnight which is stale)
    bb_current = None
    for entry in reversed(bb_values):
        if isinstance(entry, list) and len(entry) > 1 and entry[1] is not None:
            bb_current = entry[1]
            break

    # ── Stress — pull TODAY ───────────────────────────────────────────────────
    stress_raw = safe_get(lambda: client.get_stress_data(date_str), {})
    if not stress_raw or stress_raw.get("avgStressLevel", -1) == -1:
        stress_raw = safe_get(lambda: client.get_stress_data(yest_str), {})
    stress_avg = stress_raw.get("avgStressLevel") if stress_raw else None
    if stress_avg == -1:
        stress_avg = None

    # ── Resting Heart Rate — pull TODAY then fallback ─────────────────────────
    rhr_raw = safe_get(lambda: client.get_rhr_day(date_str), {})
    rhr = rhr_raw.get("allMetrics", {}).get("metricsMap", {}).get(
        "WELLNESS_RESTING_HEART_RATE", [{}])[0].get("value") if rhr_raw else None
    if not rhr:
        rhr_raw = safe_get(lambda: client.get_rhr_day(yest_str), {})
        rhr = rhr_raw.get("allMetrics", {}).get("metricsMap", {}).get(
            "WELLNESS_RESTING_HEART_RATE", [{}])[0].get("value") if rhr_raw else None
    # Also try restingHeartRate directly from stats
    if not rhr:
        stats_today = safe_get(lambda: client.get_stats(date_str), {})
        rhr = stats_today.get("restingHeartRate") if stats_today else None

    # ── VO2 Max ───────────────────────────────────────────────────────────────
    vo2_raw = safe_get(lambda: client.get_max_metrics(yest_str), {})
    vo2 = None
    if isinstance(vo2_raw, list) and vo2_raw:
        vo2 = (vo2_raw[0].get("generic", {}) or {}).get("vo2MaxPreciseValue")
    # Fallback: try user stats
    if not vo2:
        user_stats = safe_get(lambda: client.get_user_summary(yest_str), {})
        vo2 = (user_stats or {}).get("vo2Max")

    # ── Steps & Calories — pull TODAY ────────────────────────────────────────
    steps_raw = safe_get(lambda: client.get_steps_data(date_str), [])
    total_steps = 0
    if isinstance(steps_raw, list):
        for s in steps_raw:
            if isinstance(s, dict):
                total_steps += s.get("steps", 0)

    stats_raw = safe_get(lambda: client.get_stats(date_str), {})
    active_calories = stats_raw.get("activeKilocalories") if stats_raw else None
    total_calories  = stats_raw.get("totalKilocalories") if stats_raw else None

    # ── SpO2 — pull TODAY ─────────────────────────────────────────────────────
    spo2_raw = safe_get(lambda: client.get_spo2_data(date_str), {})
    spo2_avg = (spo2_raw.get("averageSpO2") or spo2_raw.get("avgSleepSpO2")
                or spo2_raw.get("lastSevenDaysAvgSpO2")) if spo2_raw else None

    # ── Last Activity — yesterday or today ────────────────────────────────────
    activities = safe_get(lambda: client.get_activities_by_date(yest_str, date_str), [])
    last_activity = {}
    if activities:
        a = activities[0]
        last_activity = {
            "type":             a.get("activityType", {}).get("typeKey"),
            "name":             a.get("activityName"),
            "duration_seconds": a.get("duration"),
            "distance_meters":  a.get("distance"),
            "avg_hr":           a.get("averageHR"),
            "max_hr":           a.get("maxHR"),
            "calories":         a.get("calories"),
            "training_load":    a.get("activityTrainingLoad"),
            "avg_pace":         a.get("averageSpeed"),
            "hr_zones":         a.get("heartRateZones", []),
        }

    # ── Assemble payload ──────────────────────────────────────────────────────
    payload = {
        "sync_date":       date_str,
        "data_date":       date_str,
        "sleep":           sleep,
        "hrv":             hrv,
        "body_battery":    {"morning": bb_current, "values": bb_values[:48]},
        "stress":          {"avg": stress_avg},
        "resting_hr":      rhr,
        "vo2_max":         vo2,
        "steps":           total_steps,
        "active_calories": active_calories,
        "total_calories":  total_calories,
        "spo2_avg":        spo2_avg,
        "last_activity":   last_activity,
    }

    # ── Push to GitHub ────────────────────────────────────────────────────────
    print(f"Pushing data to GitHub ({GITHUB_REPO})...")
    gh   = Github(GITHUB_TOKEN)
    repo = gh.get_repo(GITHUB_REPO)

    file_path = f"data/{date_str}.json"
    content   = json.dumps(payload, indent=2, ensure_ascii=False)

    try:
        existing = repo.get_contents(file_path)
        repo.update_file(file_path, f"Health data {date_str}", content, existing.sha)
        print(f"Updated {file_path}")
    except Exception:
        repo.create_file(file_path, f"Health data {date_str}", content)
        print(f"Created {file_path}")

    # Also update latest.json for the dashboard
    latest_path = "data/latest.json"
    try:
        existing = repo.get_contents(latest_path)
        repo.update_file(latest_path, f"Latest health data {date_str}", content, existing.sha)
    except Exception:
        repo.create_file(latest_path, f"Latest health data {date_str}", content)

    print(f"Done. Data saved for {yest_str}.")
    return payload

if __name__ == "__main__":
    try:
        sync()
    except Exception as e:
        print(f"ERROR: {e}")
        traceback.print_exc()
        exit(1)
