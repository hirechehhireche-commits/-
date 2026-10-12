═══════════════════════════════════════════════════════════════════
  TITAN FINAL-BOT — حزمة v129 المعتمدة  |  بناء: 2026-10-12
═══════════════════════════════════════════════════════════════════

■ المحتوى (20 ملفاً تشغيلياً — لا حطام تجارب)
    TITAN_UNIFIED_BOT.py   ← نقطة الإدخال (الواجهة الموحّدة + تيليغرام)
    titan_juggernaut_bot.py ← المحرك المعتمد T127
    live_runtime / live_execution / live_store / binance_spot
    emergency_circuit_breaker / crash_prediction_engine
    gate_data / cache_loader / mhf_bridge / micro_hedge_fund
    github_disk_v5 / titan_ultimate_failsafe / titan_content_protection
    bt5y_static / golden_split_engine(+_v130)
    requirements.txt / runtime.txt (Python 3.12.7)

■ بصمة المحرك المعتمد (تحقق بعد الفك):
    titan_juggernaut_bot.py  md5 = 187e459bfb648c523b4c2df87e6df593

■ التكوين المعتمد (داخل المحرك — لا تعدّله):
    STRATEGY1_CAPITAL = 390$  |  STRATEGY2_CAPITAL = 10$
    POOL_BUDGETS = [92, 1, 7]  →  P1 358.8 / P2 3.9 / P3 27.3
    الشهادة: +1639.9% · DD 21.06% · PF 3.26 · 504 صفقات (5Y)
    OOS أعمى: +242.6% — الوحيد الصامد خارج العينة في المشروع.

■ الإعدادات الافتراضية المؤكدة من الكود (لا تضبط ما يلي إلا بعلم):
    TITAN_STRATEGY_PROFILE = v241   ← احترافي: لا تستخدم vnext (حقل تجريبي)
    TITAN_MHF_LLM   = 0 (الافتراضي) ← LLM مطفأ: خطة غير مفعّلة على Render (402/404)
    TITAN_MHF = 1 / TITAN_JUGG = 1  ← المحركان مفعّلان كالشهادة
    BINANCE_ENV = live (الافتراضي)  ← تنفيذ حقيقي — انتبه!
    TITAN_PRIVATE = 1 | TITAN_GIT_SYNC = on | TITAN_CYCLE_DELAY = 15s

■ الأسرار: لا أسرار داخل الحزمة إطلاقاً.
    مفاتيح Telegram (BOT_TOKEN) و Binance تُدخل من متغيرات بيئة استضافتك
    أو من لوحة التحكم داخل التيليغرام حسب إعدادك المعتاد.

■ التشغيل (Render أو أي VPS):
    pip install -r requirements.txt
    python TITAN_UNIFIED_BOT.py

■ لا تشحن معك: live_execution.sqlite3* / bot_state_v241.json
    (ملفات حالة تُولد تلقائياً — نقلها قد يعيد إيقاعات قديمة)
═══════════════════════════════════════════════════════════════════
