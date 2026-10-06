"""
Cache Loader V3 - Gate Data Only - بدون bundle
يعمل بفريم 5m فقط + Resample 5m→4H كما طلب المستخدم
- إذا وجد bundle يستخدمه للباكتست
- إذا لم يوجد، يجلب حي من gate_data.py (Binance 5m)
- GitHub Friendly: لا ملفات كبيرة >25MB
"""
import pickle, gzip
from pathlib import Path

BUNDLE_PATHS = [
    Path("titan_cache_bundle.pkl.gz"),
    Path("titan_cache_bundle.pkl"),
]

_bundle_cache = None

def get_bundle():
    global _bundle_cache
    if _bundle_cache is not None:
        return _bundle_cache
    for p in BUNDLE_PATHS:
        if p.exists():
            try:
                if p.suffix == '.gz' or str(p).endswith('.gz'):
                    import gzip
                    with gzip.open(p, 'rb') as f:
                        _bundle_cache = pickle.load(f)
                else:
                    with open(p, 'rb') as f:
                        _bundle_cache = pickle.load(f)
                print(f"[CacheLoader] ✅ Bundle {p} {len(_bundle_cache)} files - للباكتست فقط")
                return _bundle_cache
            except Exception as e:
                print(f"[CacheLoader] Fail {p}: {e}")
                continue
    print(f"[CacheLoader] ℹ️ لا bundle - سيتم جلب 5m حي من gate_data.py + Resample 4H")
    return None

def load_from_bundle(key: str):
    b = get_bundle()
    if b and key in b:
        return b[key]
    return None

def load_titans_cache():
    # للباكتست فقط - إذا لا bundle نرجع None وسيتم البناء من KuCoin أو gate_data
    data = load_from_bundle("titans_4h_5y_cache")
    if data:
        return data
    print(f"[CacheLoader] ℹ️ titans_4h_5y_cache غير موجود - الباكتست سيستخدم gate_data 5m→4H")
    return None

def load_gate5m():
    return load_from_bundle("gate5m_v102")

def load_gate1m():
    return load_from_bundle("gate1m_v102")

def load_bt5y_result():
    return load_from_bundle("bt5y_static_result")
