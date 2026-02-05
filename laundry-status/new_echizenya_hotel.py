"""env-test22_no_timer_30s_commented.py

コインランドリー使用状況（乾燥機2台・洗濯機2台）を Ambient のクラウド API から取得し、
Web 画面で「使用中 / 使用可」を表示するサンプル。

仕様（重要）
- Ambient の値が THRESHOLD 以上の「間」ずっと『使用中』
- THRESHOLD を下回ったら『使用可』
- 以前あった 1分タイマー（ロック/クールダウン）機能は無し
- Web 画面は Ambient の更新頻度（30秒）に合わせて 30秒おきに再取得

起動:
  python env-test22_no_timer_30s_commented.py
  → http://localhost:5000 をブラウザで開く
"""

# Flask: Python だけで簡単に Web サーバ + API を作るためのフレームワーク
from flask import Flask, jsonify, render_template_string
import os
# requests: HTTP 通信（Ambient API にアクセスする）
import requests

# datetime/timezone: 取得時刻（サーバの現在時刻）や ISO8601 パースに使用
from datetime import datetime, timezone

# Flask アプリ本体を作成（この app にルーティングや設定を紐づける）
app = Flask(__name__)

# ===== Ambient 設定 =====

DEFAULT_CHANNEL_ID = 95641
CHANNEL_ID = int(os.getenv("AMBIENT_CHANNEL_ID", str(DEFAULT_CHANNEL_ID)))

# Ambient の Read Key（読み取り権限のキー）
# セキュリティのため、コードへ直書きせず環境変数 AMBIENT_READ_KEY から読むのがおすすめです。
READ_KEY = os.getenv("AMBIENT_READ_KEY", "")

# Ambient API のベースURL（通常はこのままでOK。必要なら AMBIENT_BASE_URL で上書き可能）
AMBIENT_BASE_URL = os.getenv("AMBIENT_BASE_URL", "http://ambidata.io")

# Ambient のデータ取得 API エンドポイント
# 例: http://ambidata.io/api/v2/channels/<CHANNEL_ID>/data
AMBIENT_URL = f"http://ambidata.io/api/v2/channels/{CHANNEL_ID}/data"

# ===== 判定ルール =====

# 「値が THRESHOLD 以上 → 使用中」「それ未満 → 使用可」
# ※このしきい値は機器・センサによって調整してください
THRESHOLD = 0.05


# ===== 表示する HTML（1枚のページとして埋め込み） =====
# render_template_string() に渡して、Python 変数（channel_id, threshold）を差し込んで表示します。
# r"""...""" は raw string（バックスラッシュ等をそのまま扱う）
HTML = r"""<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Ambient {{ channel_id }}</title>

<style>
  /* :root は HTML 全体で使える CSS 変数（色や余白など）を定義 */
  :root{ --ok:#2ecc71; --warn:#FF4C4C; --base:#f3f4f6; --fg:#111; --gap:12px; --topbar-h:48px; }

  /* すべての要素で padding/border を含めてサイズ計算したいので box-sizing を統一 */
  *{box-sizing:border-box;}

  /* ページ全体の基本スタイル */
  body{
    margin:0; padding:12px;
    font-family:system-ui,-apple-system,"Segoe UI",Roboto,"Hiragino Kaku Gothic ProN","Noto Sans JP","Yu Gothic",sans-serif;
    background:#fff; color:var(--fg);
  }

  /* 画面全体を中央寄せして、要素間に gap をつける */
  .wrap{max-width:680px;margin:0 auto;display:grid;gap:var(--gap)}

  /* 上部のバー（取得時刻の表示用） */
  .topbar{display:flex;align-items:center;gap:12px; min-height:var(--topbar-h);}

  /* 取得時刻の文字サイズ（画面幅に応じて伸縮） */
  .stamp{font-size:clamp(14px,4vw,18px);}

  /* 2列グリッド（乾燥機2台 + 洗濯機2台 を並べる） */
  .grid{display:grid; grid-template-columns:repeat(2,1fr); gap:var(--gap);}

  /* 1台ぶんのカード */
  .box{
    position:relative; border-radius:14px; padding:18px;
    display:flex; flex-direction:column; align-items:center; justify-content:center;
    background:var(--base);
    aspect-ratio:1/1.5; /* スマホ想定で縦長 */
  }

  /* 画面が広い（PC等）場合は高さを画面いっぱい使う */
  @media (min-width: 1024px){
    .wrap{max-width:680px;}
    .grid{ height:calc(100vh - var(--topbar-h) - var(--gap) - var(--gap) - 24px); grid-template-rows:repeat(2,1fr); }
    .box{aspect-ratio:auto;}
  }

  /* カード中央の大きい文字（使用中/使用可/—） */
  .val{
    font-variant-numeric:tabular-nums;
    font-weight:700; font-size:clamp(28px,9vw,44px);
    line-height:1.1; text-align:center;
  }

  /* カード左上のラベル（乾燥機/洗濯機） */
  .label{
    position:absolute; top:8px; left:10px;
    font-size:clamp(11px,2.6vw,13px); font-weight:600; opacity:.75; letter-spacing:.02em; user-select:none;
  }

  /* 使用中のときに表示する「🌀」を回転させる */
  .washer{
    margin-top: 6px;
    font-size: clamp(20px, 6vw, 28px);
    animation: washer-spin 1s linear infinite;
  }

  /* 回転アニメーション定義 */
  @keyframes washer-spin{
    from { transform: rotate(0deg); }
    to   { transform: rotate(360deg); }
  }
</style>
</head>

<body>
<div class="wrap">
  <!-- created は「Ambient 側の最新データの作成時刻」を表示する場所 -->
  <div class="topbar"><div id="created" class="stamp">--</div></div>

  <!-- 4台分のカード。id は Ambient のデータ項目（d1〜d4）に合わせる -->
  <div class="grid">
    <div class="box" id="d1">
      <span class="label">乾燥機</span>
      <span class="val">--</span>
      <div class="washer" hidden>🌀</div>
    </div>

    <div class="box" id="d2">
      <span class="label">乾燥機</span>
      <span class="val">--</span>
      <div class="washer" hidden>🌀</div>
    </div>

    <div class="box" id="d3">
      <span class="label">洗濯機</span>
      <span class="val">--</span>
      <div class="washer" hidden>🌀</div>
    </div>

    <div class="box" id="d4">
      <span class="label">洗濯機</span>
      <span class="val">--</span>
      <div class="washer" hidden>🌀</div>
    </div>
  </div>
</div>

<script>
  // ===== 画面側（ブラウザ側）のロジック =====

  // Flask 側から差し込まれる（Python の THRESHOLD をそのまま渡す）
  const THRESHOLD = {{ threshold|safe }};

  // 30秒ごとにサーバ（/api/data）へ取りに行く（Ambient の更新頻度に合わせる）
  // ※数値はミリ秒。30秒 = 30 * 1000 = 30,000ms
  const POLL_MS   = 30_000;

  // CSS 変数（--ok など）を JavaScript から参照したいときのヘルパ
  function getVar(name){
    // document.documentElement = <html> 要素
    // getComputedStyle(...) で最終的に適用されたスタイル値を取得
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  }

  // ある数値 v に対して、背景色をどれにするか決める関数（補助）
  // ※今回の表示は setAvailableView() に集約しているので、直接は使っていません。
  function colorFor(v){
    if (v === null) return getVar('--base');
    if (v >= THRESHOLD) return getVar('--warn');
    return getVar('--ok');
  }

  // 「使用中」表示をセットする関数（補助）
  // ※今回の表示は setAvailableView() に集約しているので、直接は使っていません。
  function setUsingView(key){
    const el = document.getElementById(key);       // d1〜d4 のカード要素を取る
    el.querySelector('.val').textContent = '使用中'; // カード中央の文字を書き換える

    const w = el.querySelector('.washer');         // 🌀要素を取る
    if (w) w.hidden = false;                       // hidden を外して表示する

    el.style.background = getVar('--warn');        // 背景を赤（warn）にする
  }

  // d1〜d4 それぞれについて、数値 num をもとに「使用可/使用中/—」を表示する
  // num が null のときは「値が取れない」扱い
  function setAvailableView(key, num){
    const el = document.getElementById(key);

    if(num === null){
      // 値が無い / 変換できない → 不明（—）
      el.querySelector('.val').textContent = '—';
      el.style.background = getVar('--base');
    }else if(num < THRESHOLD){
      // しきい値より小さい → 使用可
      el.querySelector('.val').textContent = '使用可';
      el.style.background = getVar('--ok');
    }else{
      // num >= THRESHOLD → 使用中（しきい値を超えている間は常に使用中）
      el.querySelector('.val').textContent = '使用中';
      el.style.background = getVar('--warn');
    }

    // 🌀は「使用中」のときだけ表示。
    // hidden=true なら非表示、false なら表示
    const w = el.querySelector('.washer');
    if (w) w.hidden = !(num !== null && num >= THRESHOLD);
  }

  // サーバ（/api/data）から返ってきた JSON を画面に反映する
  function apply(payload){
    // payload が null/undefined の可能性もあるので || {} で空オブジェクトにする
    const { created, values } = payload || {};

    // created（Ambient の created 時刻）を画面上部に表示
    // new Date(created) は ISO8601 文字列を Date に変換
    // toLocaleString() は端末のロケール（日付表示形式）で表示
    document.getElementById('created').textContent = created ? new Date(created).toLocaleString() : '—';

    // values は {d1:..., d2:..., d3:..., d4:...} の想定
    // entries で [キー, 値] の配列にしてループ
    Object.entries(values || {}).forEach(([k, v])=>{
      // v を数値に変換できなければ null にする
      // 例: null, "", NaN などを弾く
      const num = (v===null || v==="" || Number.isNaN(Number(v))) ? null : Number(v);

      // 変換後の num をもとにカードの表示を更新
      setAvailableView(k, num);
    });
  }

  // サーバから最新の状態を取得して apply() する
  async function load(){
    try{
      // ブラウザから同一サーバの /api/data に GET リクエスト
      const r = await fetch('/api/data');

      // HTTP 200-299 以外はエラー扱い
      if(!r.ok) throw new Error('HTTP '+r.status);

      // JSON として読み、画面へ反映
      apply(await r.json());
    }catch(e){
      // 取得失敗（ネットワーク不通や 502 など）
      // 上部にエラーメッセージを表示
      document.getElementById('created').textContent = '取得エラー: ' + e.message;
    }
  }

  // ページ表示直後に1回取得
  load();

  // 以降、POLL_MS（30秒）ごとに繰り返し取得
  setInterval(load, POLL_MS);
</script>
</body>
</html>"""


# ===== Flask ルーティング（URL と関数を紐づける） =====

@app.route("/")
def index():
    """トップページ（HTML を返す）"""
    # HTML テンプレートに channel_id と threshold を埋め込んで返す
    return render_template_string(HTML, channel_id=CHANNEL_ID, threshold=THRESHOLD)


@app.route("/api/data")
def api_data():
    """ブラウザが定期取得する API。

    Ambient API から最新1件を取り、
    created（時刻）と d1〜d4 の値を JSON で返す。
    """

    # Ambient の API に渡すクエリパラメータ
    # readKey: チャネルの Read Key
    # n: 何件取得するか（ここでは最新 1 件）
    params = {"readKey": READ_KEY, "n": 1}

    try:
        # Ambient API へ GET（timeout=10 秒でタイムアウト）
        r = requests.get(AMBIENT_URL, params=params, timeout=10)

        # HTTP ステータスが 4xx/5xx の場合は例外にする
        r.raise_for_status()

        # JSON を Python の list/dict に変換
        data = r.json()

        # Ambient 側にデータがまだ無い（空配列）ケース
        if not data:
            return jsonify({
                "created": None,
                "server_now": datetime.now(timezone.utc).isoformat(),
                "values": {"d1": None, "d2": None, "d3": None, "d4": None},
            })

        # 最新 1 件（n=1 なので data[0] が最新）
        row = data[0]

        # created フィールドを ISO8601 としてパース（UTC に揃える）
        created_dt = _parse_iso8601(row.get("created"))
        if created_dt is None:
            # created が壊れている等のときは ValueError を投げて下の except へ
            raise ValueError("Invalid created timestamp")

        # d1〜d4 を float に変換（失敗したら None）
        vals = {k: _to_num(row.get(k)) for k in ["d1", "d2", "d3", "d4"]}

        # ブラウザへ返す JSON
        return jsonify({
            "created": created_dt.isoformat(),
            "server_now": datetime.now(timezone.utc).isoformat(),
            "values": vals,
        })

    except requests.RequestException as e:
        # ネットワークエラー / タイムアウト / HTTP エラーなど
        return jsonify({"error": str(e)}), 502

    except ValueError as e:
        # Ambient からのレスポンス形式がおかしい等
        return jsonify({"error": f"Invalid response from Ambient: {e}"}), 502


# ===== ヘルパ関数 =====

def _to_num(v):
    """Ambient の値（文字列 or 数値）を float に変換。

    変換できない場合は None を返す。
    """
    try:
        # None や空文字は「値なし」として None にする
        if v is None or v == "":
            return None

        # 文字列 "4.2" や 数値 4.2 を float に統一
        return float(v)

    except (TypeError, ValueError):
        # 変換できない型/文字列の場合
        return None


def _parse_iso8601(s: str):
    """ISO8601 文字列（Ambient の created）を datetime に変換。

    - 末尾が 'Z' の場合: UTC（+00:00）として扱う
    - タイムゾーンが無い場合: UTC とみなす
    - 失敗したら None
    """

    # 空文字や None を弾く
    if not s:
        return None

    try:
        # "2025-12-22T00:00:00Z" のような末尾 Z を +00:00 に置換
        if s.endswith("Z"):
            return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)

        # fromisoformat は "YYYY-MM-DDTHH:MM:SS+09:00" 等をパースできる
        dt = datetime.fromisoformat(s)

        # タイムゾーン情報が無い（naive datetime）場合は UTC とみなす
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)

        # 最終的に UTC に揃えて返す
        return dt.astimezone(timezone.utc)

    except Exception:
        # どんな例外でも None を返す（壊れた created 等）
        return None


# このファイルが「直接 python で実行」された時だけ、開発用サーバを起動
# （他のファイルから import された時は起動しない）
if __name__ == "__main__":
    # host=0.0.0.0: 外部（同一ネットワーク）からもアクセス可能
    # port=5000: 5000 番ポートで待ち受け
    # debug=True: 開発用（エラー詳細表示・自動リロード）
    app.run(host="0.0.0.0", port=8080, debug=False)
