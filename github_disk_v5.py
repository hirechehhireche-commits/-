"""
TitanGitHubSync v6 — قناة الحفظ في GitHub (M1)
==================================================================
- ملفان في ريبو خاص: titan-state.json (حالة البوت: صفقات+ورقي+بصمات) و titan-live.blob (لقطة SQLite مشفرة)
- غير حظرية كلياً: طابور latest-wins لكل ملف + خيط Daemon + خنق معدل + خصم تكرار بالهاش
- استرجاع عند الإقلاع فقط إذا الملف المحلي غائب (نهج كاتب-واحد — لا يمس أبداً ملفاً موجوداً)
- قاطع طوارئ: TITAN_GIT_SYNC=off يعطل كل شيء فوراً بدون إعادة نشر
البيئة المطلوبة: GITHUB_TOKEN (contents:rw على ريبو واحد) + GITHUB_REPO=owner/repo (خاص)
"""
import base64
import hashlib
import json
import os
import threading
import time
from datetime import datetime, timezone

try:
    import requests
except ImportError:  # الحماية ضد بيئة ناقصة — القناة تُعطّل ذاتياً
    requests = None

GITHUB_TOKEN = (os.environ.get("GITHUB_TOKEN") or "").strip()
GITHUB_REPO = (os.environ.get("GITHUB_REPO") or "").strip()  # owner/repo
GITHUB_BRANCH = (os.environ.get("GITHUB_BRANCH") or "main").strip() or "main"
SYNC_ENABLED = (os.environ.get("TITAN_GIT_SYNC") or "on").strip().lower() not in ("off", "0", "false")

STATE_REMOTE = "titan-state.json"
LIVE_REMOTE = "titan-live.blob"

# خنق المعدل: لا رفع لنفس الملف أكثر من مرة خلال الفجوة (حماية Rate Limit + تاريخ git نظيف)
MIN_PUSH_GAP_SEC = float(os.environ.get("TITAN_GIT_MIN_GAP", "60"))
EVENT_PUSH_GAP_SEC = float(os.environ.get("TITAN_GIT_EVENT_GAP", "30"))  # أحداث فتح/إغلاق الصفقات
_TIMEOUT = 20


def _ready() -> bool:
    return bool(SYNC_ENABLED and requests is not None and GITHUB_TOKEN and GITHUB_REPO)


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class TitanGitHubSync:
    """مزامن GitHub غير حظري — مثيل واحد للبوت كله."""

    def __init__(self, logger=None):
        self._log = logger or (lambda m: print(m, flush=True))
        self._pending = {}            # remote_name -> (raw_bytes, urgent, sha256)
        self._cv = threading.Condition()
        self._pushed_hash = {}        # remote_name -> last pushed sha256 (خصم التكرار)
        self._last_push = {}          # remote_name -> epoch آخر رفع ناجح
        self.stats = {"pushed": 0, "skipped_dup": 0, "errors": 0}
        self._thread = None

    # ---------------- واجهات الرفع (غير حظرية) ----------------
    def push(self, remote_name: str, payload, urgent: bool = False) -> bool:
        """جدولة رفع. latest-wins: مواد أقدم لنفس الملف تُستبدل فوراً."""
        if not _ready():
            return False
        try:
            raw = payload if isinstance(payload, (bytes, bytearray)) else \
                json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
            h = hashlib.sha256(bytes(raw)).hexdigest()
            with self._cv:
                if self._pushed_hash.get(remote_name) == h:
                    self.stats["skipped_dup"] += 1
                    return True
                self._pending[remote_name] = (bytes(raw), bool(urgent), h)
                self._cv.notify_all()
            return True
        except Exception as e:
            self._log(f"[GIT-SYNC] ⚠️ push err {remote_name}: {e}")
            return False

    def push_state_file(self, local_path: str, urgent: bool = False) -> bool:
        """يرفع محتوى ملف الحالة المحلي المكتوب حديثاً (يُستدعى بعد save_state)."""
        try:
            if not (local_path and os.path.exists(local_path)):
                return False
            with open(local_path, "rb") as f:
                raw = f.read()
            return self.push(STATE_REMOTE, raw, urgent=urgent)
        except Exception as e:
            self._log(f"[GIT-SYNC] ⚠️ state read err: {e}")
            return False

    def push_live_blob(self, blob_bytes: bytes, urgent: bool = False) -> bool:
        """رفع لقطة SQLite المشفرة (تصديرها عبر LiveStore.export_snapshot)."""
        if not blob_bytes:
            return False
        return self.push(LIVE_REMOTE, blob_bytes, urgent=urgent)

    # ---------------- الاسترجاع عند الإقلاع ----------------
    def _fetch_remote(self, remote_name: str):
        """يرجع raw bytes أو None (لا يرفع استثناءات نحو الخارج أبداً)."""
        if not _ready():
            return None
        url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{remote_name}"
        headers = {
            "Authorization": f"Bearer {GITHUB_TOKEN}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        try:
            r = requests.get(url, headers=headers, params={"ref": GITHUB_BRANCH}, timeout=_TIMEOUT)
            if r.status_code == 200:
                return base64.b64decode(r.json().get("content", ""))
            if r.status_code == 404:
                self._log(f"[GIT-SYNC] ℹ️ {remote_name} غير موجود في الريبو (أول تشغيل)")
            else:
                self._log(f"[GIT-SYNC] ⚠️ fetch {remote_name}: HTTP {r.status_code}: {r.text[:120]}")
        except Exception as e:
            self._log(f"[GIT-SYNC] ⚠️ fetch {remote_name} err: {e}")
        return None

    @staticmethod
    def _atomic_write(path: str, raw: bytes) -> bool:
        tmp = f"{path}.restore-tmp"
        try:
            parent = os.path.dirname(os.path.abspath(path))
            os.makedirs(parent, exist_ok=True)
            with open(tmp, "wb") as f:
                f.write(raw)
                f.flush()
            try:
                os.chmod(tmp, 0o600)
            except OSError:
                pass
            os.replace(tmp, path)
            return True
        except Exception:
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            except OSError:
                pass
            return False

    def restore_state_if_missing(self, local_path: str) -> bool:
        """يسترجع titan-state.json فقط إذا كان الملف المحلي غائباً — كاتب-واحد: لا يمس ملفاً موجوداً."""
        if os.path.exists(local_path):
            return False
        raw = self._fetch_remote(STATE_REMOTE)
        if not raw:
            return False
        try:
            json.loads(raw.decode("utf-8"))  # تحقق أن المحتوى JSON سليم قبل الكتابة
        except Exception:
            self._log("[GIT-SYNC] ❌ النسخة البعيدة للحالة تالفة (ليست JSON) — تم تجاهلها")
            return False
        if self._atomic_write(local_path, raw):
            self._log(f"[GIT-SYNC] ✅ تم استرجاع حالة البوت من GitHub ({len(raw)} بايت) → {local_path}")
            return True
        self._log(f"[GIT-SYNC] ❌ فشلت كتابة الحالة المسترجعة → {local_path}")
        return False

    def restore_live_if_missing(self, local_db_path: str) -> bool:
        """يسترجع لقطة live DB فقط إذا كانت غائبة، مع التحقق من ترويسة SQLite."""
        if os.path.exists(local_db_path):
            return False
        raw = self._fetch_remote(LIVE_REMOTE)
        if not raw:
            return False
        if raw[:16] != b"SQLite format 3\x00":
            self._log("[GIT-SYNC] ❌ النسخة البعيدة للـ live DB ليست SQLite سليمة — تم تجاهلها")
            return False
        if self._atomic_write(local_db_path, raw):
            self._log(f"[GIT-SYNC] ✅ تم استرجاع قاعدة live من GitHub ({len(raw)} بايت) → {local_db_path}")
            return True
        self._log(f"[GIT-SYNC] ❌ فشلت كتابة قاعدة live المسترجعة → {local_db_path}")
        return False

    # ---------------- الخيط الداخلي ----------------
    def start(self, logger=None) -> bool:
        """يبدأ خيط المزامنة (مرة واحدة فقط). آمن للاستدعاء المتكرر."""
        if logger is not None:
            self._log = logger
        if not _ready():
            if SYNC_ENABLED:
                self._log("[GIT-SYNC] ⚠️ معطل: GITHUB_TOKEN/GITHUB_REPO غير مضبوطين (أو TITAN_GIT_SYNC=off)")
                if not SYNC_ENABLED:
                    self._log("[GIT-SYNC] معطل يدوياً عبر TITAN_GIT_SYNC=off")
            return False
        if self._thread and self._thread.is_alive():
            return True
        self._thread = threading.Thread(target=self._worker, daemon=True, name="git-sync")
        self._thread.start()
        self._log(f"[GIT-SYNC] ✅ قناة الحفظ نشطة → {GITHUB_REPO}@{GITHUB_BRANCH} "
                  f"(خنق {MIN_PUSH_GAP_SEC:.0f}s/{EVENT_PUSH_GAP_SEC:.0f}s)")
        return True

    def _worker(self):
        while True:
            try:
                with self._cv:
                    while not self._pending:
                        self._cv.wait(timeout=300)  # سكون تام بلا استهلاك CPU
                    items = list(self._pending.items())
                    self._pending.clear()
                for name, (raw, urgent, h) in items:
                    gap = EVENT_PUSH_GAP_SEC if urgent else MIN_PUSH_GAP_SEC
                    self._do_push(name, raw, h, gap)
            except Exception as e:
                self.stats["errors"] += 1
                self._log(f"[GIT-SYNC] ⚠️ worker err: {e}")
                time.sleep(5)

    def _do_push(self, name: str, raw: bytes, h: str, gap: float):
        if self._pushed_hash.get(name) == h:  # خصم تكرار أخير قبل الطلب
            self.stats["skipped_dup"] += 1
            return
        wait = self._last_push.get(name, 0) + gap - time.time()
        if wait > 0:
            time.sleep(wait)  # الخنق يحدث في الخيط الخامل فقط — لا يحظر أي مسار تداول
        url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{name}"
        headers = {
            "Authorization": f"Bearer {GITHUB_TOKEN}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        try:
            sha = None
            r = requests.get(url, headers=headers, params={"ref": GITHUB_BRANCH}, timeout=_TIMEOUT)
            if r.status_code == 200:
                sha = r.json().get("sha")
            body = {
                "message": f"titan-sync {name} {_utc_iso()}",
                "content": base64.b64encode(raw).decode(),
                "branch": GITHUB_BRANCH,
            }
            if sha:
                body["sha"] = sha
            pr = requests.put(url, headers=headers, json=body, timeout=_TIMEOUT)
            if pr.status_code in (200, 201):
                self._pushed_hash[name] = h
                self._last_push[name] = time.time()
                self.stats["pushed"] += 1
                self._log(f"[GIT-SYNC] 💾 رُفع {name} ({len(raw)} بايت) بأمان")
            else:
                self.stats["errors"] += 1
                self._log(f"[GIT-SYNC] ⚠️ رفع {name}: HTTP {pr.status_code}: {pr.text[:120]}")
        except Exception as e:
            self.stats["errors"] += 1
            self._log(f"[GIT-SYNC] ⚠️ رفع {name} err: {e}")


# المثيل الموحّد (يُربط باللوجر الرئيسي عند الإقلاع عبر start(logger=log))
GIT_SYNC = TitanGitHubSync()
