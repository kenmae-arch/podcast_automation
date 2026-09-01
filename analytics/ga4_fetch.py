"""GA4 Data API から albumatlas.jp の日次データを取得して store.json にマージする。

必要な環境変数:
  GA4_PROPERTY_ID            GA4のプロパティID(数字のみ。例: 123456789)
  GA4_SERVICE_ACCOUNT_JSON   サービスアカウント鍵JSONの中身(文字列そのまま)
  または GA4_SERVICE_ACCOUNT_FILE  鍵JSONファイルのパス

初回実行時は過去28日分をバックフィルし、以降は直近3日を取り直す
(GA4の集計は数日遅れて確定することがあるため)。
"""
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

STORE_PATH = Path(__file__).resolve().parent / "data" / "store.json"
JST = timezone(timedelta(hours=9))


def load_store():
    return json.loads(STORE_PATH.read_text(encoding="utf-8"))


def save_store(store):
    store["meta"]["lastUpdated"] = datetime.now(JST).isoformat(timespec="seconds")
    STORE_PATH.write_text(
        json.dumps(store, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def get_credentials():
    from google.oauth2 import service_account

    raw = os.getenv("GA4_SERVICE_ACCOUNT_JSON", "").strip()
    path = os.getenv("GA4_SERVICE_ACCOUNT_FILE", "").strip()
    if raw:
        info = json.loads(raw)
        creds = service_account.Credentials.from_service_account_info(info)
    elif path:
        creds = service_account.Credentials.from_service_account_file(path)
    else:
        return None
    return creds.with_scopes(["https://www.googleapis.com/auth/analytics.readonly"])


def run_report(creds, property_id, body):
    import requests
    from google.auth.transport.requests import Request

    if not creds.valid:
        creds.refresh(Request())
    url = f"https://analyticsdata.googleapis.com/v1beta/properties/{property_id}:runReport"
    resp = requests.post(
        url,
        headers={"Authorization": f"Bearer {creds.token}"},
        json=body,
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()


def merge_daily(store, start_date, end_date, creds, property_id):
    """日次のusers/newUsers/sessions/pageviewsを取得してマージ。"""
    body = {
        "dateRanges": [{"startDate": start_date, "endDate": end_date}],
        "dimensions": [{"name": "date"}],
        "metrics": [
            {"name": "totalUsers"},
            {"name": "newUsers"},
            {"name": "sessions"},
            {"name": "screenPageViews"},
        ],
        "limit": 400,
    }
    data = run_report(creds, property_id, body)
    ga4 = store["web"].setdefault("ga4", {})
    keys = ["users", "newUsers", "sessions", "pageviews"]
    for row in data.get("rows", []):
        d = row["dimensionValues"][0]["value"]  # YYYYMMDD
        date = f"{d[0:4]}-{d[4:6]}-{d[6:8]}"
        for i, key in enumerate(keys):
            ga4.setdefault(key, {})[date] = int(row["metricValues"][i]["value"])


def merge_breakdown(store, date, dimension, store_key, creds, property_id, limit=8):
    """指定日のページ別/チャネル別内訳を取得してマージ。"""
    body = {
        "dateRanges": [{"startDate": date, "endDate": date}],
        "dimensions": [{"name": dimension}],
        "metrics": [{"name": "screenPageViews" if store_key == "topPages" else "sessions"}],
        "orderBys": [{"metric": {"metricName": "screenPageViews" if store_key == "topPages" else "sessions"}, "desc": True}],
        "limit": limit,
    }
    data = run_report(creds, property_id, body)
    rows = [
        [r["dimensionValues"][0]["value"], int(r["metricValues"][0]["value"])]
        for r in data.get("rows", [])
    ]
    if rows:
        store["web"]["ga4"].setdefault(store_key, {})[date] = rows


def main():
    property_id = os.getenv("GA4_PROPERTY_ID", "").strip()
    store = load_store()
    conn = store["meta"]["connections"].setdefault("ga4", {})
    try:
        creds = get_credentials()
    except Exception as e:  # 鍵JSONが壊れている等
        conn.update({"state": "error", "note": f"認証情報の読み込みに失敗: {e}"})
        save_store(store)
        print(f"[ga4] 認証情報エラー: {e}", file=sys.stderr)
        return 1

    if not property_id or creds is None:
        conn.update(
            {"state": "pending", "note": "GA4_PROPERTY_ID / サービスアカウント鍵が未設定"}
        )
        save_store(store)
        print("[ga4] 未設定のためスキップ(GA4_PROPERTY_ID / GA4_SERVICE_ACCOUNT_JSON)")
        return 0

    today = datetime.now(JST).date()
    yesterday = today - timedelta(days=1)
    has_history = bool(store["web"].get("ga4", {}).get("users"))
    start = yesterday - timedelta(days=2 if has_history else 27)
    try:
        merge_daily(store, start.isoformat(), yesterday.isoformat(), creds, property_id)
        merge_breakdown(store, yesterday.isoformat(), "pagePath", "topPages", creds, property_id)
        merge_breakdown(store, yesterday.isoformat(), "sessionDefaultChannelGroup", "channels", creds, property_id)
        conn.update({"state": "ok", "note": f"{yesterday.isoformat()} まで取得済み"})
        print(f"[ga4] {start} 〜 {yesterday} を取得しました")
    except Exception as e:
        conn.update({"state": "error", "note": f"取得失敗: {e}"})
        print(f"[ga4] 取得失敗: {e}", file=sys.stderr)
        save_store(store)
        return 1
    save_store(store)
    return 0


if __name__ == "__main__":
    sys.exit(main())
