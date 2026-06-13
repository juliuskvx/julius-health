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
    if not sleep_raw or not sleep_raw.get("dailySleepDTO", {}).get("sleepTimeSeconds"):
        sleep_raw = safe_get(lambda: client.get_sleep_data(yest_str), {})
    sleep_data = sleep_raw.get("dailySleepDTO", {}) if sleep_raw else {}

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

    # ── HRV ───────────────────────────────────────────────────────────────────
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

    # ── Body Battery ──────────────────────────────────────────────────────────
    bb_raw = safe_get(lambda: client.get_body_battery(date_str), [])
    bb_values = []
    if isinstance(bb_raw, list):
        for item in bb_raw:
            if isinstance(item, dict) and "bodyBatteryValuesArray" in item:
                bb_values = item["bodyBatteryValuesArray"]
                break
    # Use the MAX value reached so far today (overnight recharge peak,
    # typically reached around 5-7am) — this matches the "morning" Body
    # Battery number shown on Garmin Connect, not first or last reading.
    bb_current = None
    for entry in bb_values:
        if isinstance(entry, list) and len(entry) > 1 and entry[1] is not None:
            if bb_current is None or entry[1] > bb_current:
                bb_current = entry[1]

    # ── Training Readiness (Garmin's official score) ──────────────────────────
    tr_raw = safe_get(lambda: client.get_training_readiness(date_str), [])
    if not tr_raw:
        tr_raw = safe_get(lambda: client.get_training_readiness(yest_str), [])
    tr_entry = tr_raw[0] if isinstance(tr_raw, list) and tr_raw else {}
    training_readiness = {
        "score": tr_entry.get("score"),
        "level": tr_entry.get("level"),
        "feedback_long": tr_entry.get("feedbackLong"),
        "sleep_score": tr_entry.get("sleepScore"),
        "hrv_factor": tr_entry.get("hrvFactorPercent"),
        "recovery_time_factor": tr_entry.get("recoveryTimeFactorPercent"),
        "acwr_factor": tr_entry.get("acuteLoadFactorPercent"),
        "sleep_history_factor": tr_entry.get("sleepHistoryFactorPercent"),
    }

    # ── Stress ────────────────────────────────────────────────────────────────
    stress_raw = safe_get(lambda: client.get_stress_data(date_str), {})
    if not stress_raw or stress_raw.get("avgStressLevel", -1) == -1:
        stress_raw = safe_get(lambda: client.get_stress_data(yest_str), {})
    stress_avg = stress_raw.get("avgStressLevel") if stress_raw else None
    if stress_avg == -1:
        stress_avg = None

    # ── Resting Heart Rate ────────────────────────────────────────────────────
    rhr_raw = safe_get(lambda: client.get_rhr_day(date_str), {})
    rhr = rhr_raw.get("allMetrics", {}).get("metricsMap", {}).get(
        "WELLNESS_RESTING_HEART_RATE", [{}])[0].get("value") if rhr_raw else None
    if not rhr:
        rhr_raw = safe_get(lambda: client.get_rhr_day(yest_str), {})
        rhr = rhr_raw.get("allMetrics", {}).get("metricsMap", {}).get(
            "WELLNESS_RESTING_HEART_RATE", [{}])[0].get("value") if rhr_raw else None
    if not rhr:
        stats_today = safe_get(lambda: client.get_stats(date_str), {})
        rhr = stats_today.get("restingHeartRate") if stats_today else None

    # ── VO2 Max ───────────────────────────────────────────────────────────────
    vo2 = None
    # Scan back up to 30 days to find last known VO2 max (only updates after outdoor runs)
    for days_back in range(1, 31):
        check_date = (today - datetime.timedelta(days=days_back)).isoformat()
        vo2_raw = safe_get(lambda d=check_date: client.get_max_metrics(d), {})
        if isinstance(vo2_raw, list) and vo2_raw:
            vo2 = (vo2_raw[0].get("generic", {}) or {}).get("vo2MaxPreciseValue")
        if not vo2:
            user_stats = safe_get(lambda d=check_date: client.get_user_summary(d), {})
            vo2 = (user_stats or {}).get("vo2Max")
        if vo2:
            print(f"VO2 max found from {check_date}: {vo2}")
            break

    # ── Steps & Calories ──────────────────────────────────────────────────────
    steps_raw = safe_get(lambda: client.get_steps_data(date_str), [])
    total_steps = 0
    if isinstance(steps_raw, list):
        for s in steps_raw:
            if isinstance(s, dict):
                total_steps += s.get("steps", 0)

    stats_raw = safe_get(lambda: client.get_stats(date_str), {})
    active_calories = stats_raw.get("activeKilocalories") if stats_raw else None
    total_calories  = stats_raw.get("totalKilocalories") if stats_raw else None

    # ── SpO2 ──────────────────────────────────────────────────────────────────
    spo2_raw = safe_get(lambda: client.get_spo2_data(date_str), {})
    spo2_avg = (spo2_raw.get("averageSpO2") or spo2_raw.get("avgSleepSpO2")
                or spo2_raw.get("lastSevenDaysAvgSpO2")) if spo2_raw else None

    # ── ALL Activities — yesterday and today ──────────────────────────────────
    raw_activities = safe_get(lambda: client.get_activities_by_date(yest_str, date_str), [])
    activities = []
    if raw_activities:
        for a in raw_activities:
            activities.append({
                "type":             a.get("activityType", {}).get("typeKey"),
                "name":             a.get("activityName"),
                "start_time":       a.get("startTimeLocal"),
                "duration_seconds": a.get("duration"),
                "distance_meters":  a.get("distance"),
                "avg_hr":           a.get("averageHR"),
                "max_hr":           a.get("maxHR"),
                "calories":         a.get("calories"),
                "training_load":    a.get("activityTrainingLoad"),
                "avg_pace":         a.get("averageSpeed"),
                "hr_zones":         a.get("heartRateZones", []),
            })

    # Keep last_activity as first entry for backwards compatibility with CSV
    last_activity = activities[0] if activities else {}

    # ── Assemble payload ──────────────────────────────────────────────────────
    payload = {
        "sync_date":       date_str,
        "data_date":       date_str,
        "sleep":           sleep,
        "hrv":             hrv,
        "body_battery":    {"morning": bb_current, "values": bb_values[:48]},
        "training_readiness": training_readiness,
        "stress":          {"avg": stress_avg},
        "resting_hr":      rhr,
        "vo2_max":         vo2,
        "steps":           total_steps,
        "active_calories": active_calories,
        "total_calories":  total_calories,
        "spo2_avg":        spo2_avg,
        "last_activity":   last_activity,
        "activities":      activities,
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

    latest_path = "data/latest.json"
    try:
        existing = repo.get_contents(latest_path)
        repo.update_file(latest_path, f"Latest health data {date_str}", content, existing.sha)
    except Exception:
        repo.create_file(latest_path, f"Latest health data {date_str}", content)

    # ── Update history.csv ────────────────────────────────────────────────────
    CSV_HEADERS = [
        "date",
        "sleep_score", "sleep_hours", "deep_min", "rem_min", "light_min", "awake_min",
        "hrv_last_night", "hrv_weekly_avg", "hrv_status",
        "body_battery_morning",
        "training_readiness_score", "training_readiness_level",
        "resting_hr",
        "vo2_max",
        "stress_avg",
        "spo2_avg",
        "steps", "active_calories", "total_calories",
        "activity_type", "activity_name", "activity_distance_km",
        "activity_duration_min", "activity_avg_hr", "activity_max_hr",
        "activity_calories", "activity_training_load",
    ]

    def csv_val(val, decimals=None):
        if val is None:
            return ""
        if decimals is not None:
            return str(round(float(val), decimals))
        return str(val)

    sl  = payload["sleep"]
    act = last_activity
    new_row = ",".join([
        csv_val(date_str),
        csv_val(sl.get("score")),
        csv_val(sl["duration_seconds"] / 3600 if sl.get("duration_seconds") else None, 2),
        csv_val(round(sl["deep_seconds"]  / 60) if sl.get("deep_seconds")  else None),
        csv_val(round(sl["rem_seconds"]   / 60) if sl.get("rem_seconds")   else None),
        csv_val(round(sl["light_seconds"] / 60) if sl.get("light_seconds") else None),
        csv_val(round(sl["awake_seconds"] / 60) if sl.get("awake_seconds") else None),
        csv_val(payload["hrv"].get("last_night")),
        csv_val(payload["hrv"].get("weekly_avg")),
        csv_val(payload["hrv"].get("status")),
        csv_val(payload["body_battery"].get("morning")),
        csv_val(payload["training_readiness"].get("score")),
        csv_val(payload["training_readiness"].get("level")),
        csv_val(payload["resting_hr"]),
        csv_val(payload["vo2_max"], 1),
        csv_val(payload["stress"].get("avg")),
        csv_val(payload["spo2_avg"]),
        csv_val(payload["steps"]),
        csv_val(payload["active_calories"]),
        csv_val(payload["total_calories"]),
        csv_val(act.get("type")),
        csv_val(act.get("name")),
        csv_val(round(act["distance_meters"] / 1000, 2) if act.get("distance_meters") else None),
        csv_val(round(act["duration_seconds"] / 60, 1) if act.get("duration_seconds") else None),
        csv_val(act.get("avg_hr")),
        csv_val(act.get("max_hr")),
        csv_val(act.get("calories")),
        csv_val(act.get("training_load")),
    ])

    csv_path = "data/history.csv"
    try:
        existing_csv = repo.get_contents(csv_path)
        old_content  = existing_csv.decoded_content.decode("utf-8")
        lines = old_content.strip().splitlines()
        data_lines = [l for l in lines if l and not l.startswith("date,") and not l.startswith(date_str + ",")]
        new_content = "\n".join([",".join(CSV_HEADERS)] + data_lines + [new_row]) + "\n"
        repo.update_file(csv_path, f"History update {date_str}", new_content, existing_csv.sha)
        print(f"Updated {csv_path}")
    except Exception:
        new_content = ",".join(CSV_HEADERS) + "\n" + new_row + "\n"
        repo.create_file(csv_path, f"Create history.csv {date_str}", new_content)
        print(f"Created {csv_path}")

    print(f"Done. Data saved for {yest_str}.")
    return payload

if __name__ == "__main__":
    try:
        sync()
    except Exception as e:
        print(f"ERROR: {e}")
        traceback.print_exc()
        exit(1)
