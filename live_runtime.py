"""Telegram/HTTPS integration — v241 EASY DIRECT — إضافة سهلة مباشرة في البوت + وضع تراكمي
- يدعم طريقتين: صفحة HTTPS الآمنة (موصى بها) + كتابة مباشرة في البوت مع حذف تلقائي
"""
import hashlib
import html
import os
import secrets
import threading
import time
from urllib.parse import parse_qs,urlparse
from live_store import LiveStore
from live_execution import LiveExecutor

B=None; STORE=None; EXEC=None
TOKENS={}; CONFIRMS={}; TOKEN_LOCK=threading.Lock(); RATE={}
PUBLIC_URL=''; STOP=threading.Event(); LAST_TICK=0
EASY_TIMEOUT=300  # 5 دقائق مهلة إدخال المفتاح

def init(bot):
    global B,STORE,EXEC,PUBLIC_URL
    if bot is not None:
        B=bot
    if STORE is not None and EXEC is not None:
        return
    # افتراضيات مجانية 100% — لا تحتاج env
    venue=os.environ.get('BINANCE_ENV','live') or 'live'  # افتراضي live
    PUBLIC_URL=os.environ.get('PUBLIC_BASE_URL',os.environ.get('RENDER_EXTERNAL_URL','')).rstrip('/')
    if PUBLIC_URL:
        u=urlparse(PUBLIC_URL)
        if u.scheme!='https' or not u.netloc or u.username or u.password or u.path not in ('','/') or u.query or u.fragment:
            raise ValueError('PUBLIC_BASE_URL must be an HTTPS origin without a path')
    ws_dir = getattr(B, 'WORKSPACE_DIR', os.getcwd()) if B else os.getcwd()
    try:
        os.makedirs(ws_dir, exist_ok=True)
    except PermissionError:
        ws_dir = os.getcwd()
        try:
            os.makedirs(ws_dir, exist_ok=True)
        except:
            pass
    path=os.environ.get('TITAN_LIVE_DB',os.path.join(ws_dir,'live_execution.sqlite3'))
    # APP_SECRET افتراضي — مشتق من BOT_TOKEN إذا لم يضبط — يبقى ثابت طالما BOT_TOKEN ثابت
    app_secret=os.environ.get('APP_SECRET','')
    if not app_secret:
        bot_token=os.environ.get('BOT_TOKEN','')
        admin_id = getattr(B, 'ADMIN_CHAT_ID', '') if B else ''
        base=(bot_token+'|titan-v241-free-default-secret|'+str(admin_id))
        app_secret=hashlib.sha256(base.encode()).hexdigest()  # 64 حرف
        if B and hasattr(B, 'log'):
            B.log('[LIVE] APP_SECRET غير مضبوط — استخدام سر افتراضي مشتق من BOT_TOKEN (مجاني)')
    STORE=LiveStore(path,app_secret,venue)
    allow_live_str=os.environ.get('ALLOW_LIVE_TRADING','1')
    allow_live = allow_live_str!='0'
    pool_params = getattr(B, 'POOL_PARAMS_MAP', {}) if B else {}
    EXEC=LiveExecutor(STORE, pool_params, allow_live)
    if EXEC.allow_live:
        try:
            STORE.cipher()
        except Exception as e:
            if B and hasattr(B, 'log'):
                B.log(f'[LIVE] Cipher warning: {e}')
    try:
        import fcntl
        lockfile=open(str(path)+'.lock','a+')
        try:fcntl.flock(lockfile,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError:raise RuntimeError('Another bot process owns this execution database') from None
        STORE.process_lock=lockfile
    except ImportError:
        pass
    threading.Thread(target=worker,name='binance-execution',daemon=True).start()
    threading.Thread(target=notifier,name='telegram-outbox',daemon=True).start()

def worker():
    global LAST_TICK
    while not STOP.is_set():
        try:
            EXEC.tick()
            LAST_TICK=time.time()
        except Exception as e:
            B.log('[LIVE] '+type(e).__name__+' — check runtime/ledger')
        STOP.wait(max(5,int(os.environ.get('TITAN_ORDER_POLL','10'))))

def notifier():
    while not STOP.is_set():
        try:STORE.flush(lambda uid,text:B.send_msg(uid,text,B.more_kb()))
        except Exception:B.log('[OUTBOX] delivery will retry')
        STOP.wait(3)

def account(uid):return STORE.account(uid) if STORE else {'credential':None,'enabled':False,'capital':400,'max_order':100,'use_full_balance':False,'positions':{},'halt':None}

def panel(u):
    a=account(u['id']);active=EXEC.active(a) if EXEC else []
    venue=STORE.venue if STORE else os.environ.get('BINANCE_ENV','live')
    label='حقيقي - Binance Spot' if venue=='live' else 'تجريبي - Testnet'
    if not a.get('credential'):
        capital_text = "💵 غير مربوط - اضغط ربط binance"
    elif a.get('use_full_balance') or a.get('capital',0)==0:
        capital_text = "💎 كامل الرصيد تراكمي ✅"
    else:
        capital_text = f'💵 مخصص: {a["capital"]:g} | سقف: {a["max_order"]:g}'
    equity_info = ""
    status_icon = "✅" if a.get('credential') else "❌"
    trade_icon = "🟢 مفعّل" if a.get('enabled') else "🔴 متوقف"
    if a.get('credential') and EXEC:
        try:
            total_eq, free, used = EXEC.get_total_equity(a, EXEC.client(a))
            equity_info = (
                f"━━━━━━━━━━━━━━\n"
                f"📊 <b>رصيدك الحقيقي:</b>\n"
                f"• الإجمالي: <b>{total_eq:.2f} USDT</b>\n"
                f"• الحر: {free:.2f} | المستخدم: {used:.2f}\n"
            )
        except Exception: pass
    # نص مختصر وصادق يطابق الواقع
    if not a.get('credential'):
        return (
            f"🚀 <b>لوحة التداول</b>\n"
            f"━━━━━━━━━━━━━━\n"
            f"🌐 {label}\n"
            f"🔐 الربط: {status_icon} غير مربوط\n"
            f"⚡ التداول: {trade_icon}\n"
            f"{capital_text}\n"
            f"📂 مراكز: {len(active)}\n"
            "━━━━━━━━━━━━━━\n"
            "💡 اربط Binance لبدء التداول الحقيقي\n"
        )
    return (
        f"🚀 <b>لوحة التداول</b>\n"
        f"━━━━━━━━━━━━━━\n"
        f"🌐 {label}\n"
        f"🔐 الربط: {status_icon} مربوط ومشفّر\n"
        f"⚡ التداول: {trade_icon}\n"
        f"{capital_text}\n"
        f"📂 مراكز: {len(active)}\n"
        + equity_info +
        (f"⚠️ {B.esc(a['halt'])}\n" if a.get('halt') else '') +
        "━━━━━━━━━━━━━━\n"
        "💡 الدخول بإشارات جديدة فقط\n"
    )

def keyboard(u):
    bt=B.bt;rows=[];a=account(u['id'])
    # تصميم عصري منظم — مجموعات واضحة
    if not a.get('credential'):
        # غير مربوط — أزرار ربط
        rows.append([bt('ربط binance', 'api:easy_full')])
    else:
        # مربوط — حالة + إدارة
        rows.append([bt('👁️ أرصدتي', 'api:bal'), bt('📂 مراكزي', 'api:orders')])
        rows.append([bt('⚡ تفعيل التداول', 'api:real'), bt('📝 إيقاف الشراء', 'api:paper')])
        rows.append([bt('ربط binance', 'api:easy_full')])
        rows.append([bt('🛑 إغلاق طارئ', 'api:kill'), bt('🗑️ حذف المفتاح', 'api:del')])
        if not a.get('use_full_balance'):
            rows.append([bt('💎 تفعيل كامل الرصيد', 'api:full')])
    rows.append([bt('🏠 الرئيسية', 'nav:more')])
    return rows

def make_token(uid):
    # تم إزالة ربط الصفحة الآمنة حسب طلب المستخدم - استخدم الربط المباشر في البوت فقط
    raise ValueError('ربط الصفحة الآمنة تم إزالته - استخدم زر ربط binance المباشر في البوت')

def consume_token(token):
    raise ValueError('ربط الصفحة تم إزالته')

def start_easy_flow(uid, full_mode=True):
    """بدء تدفق الإدخال السهل المباشر"""
    st=B.load_state()
    user=st['users'].get(str(uid))
    if not user:
        return
    # لا يمكن تغيير المفتاح بوجود مراكز
    a=account(uid)
    if EXEC and (EXEC.active(a) or STORE.unresolved(uid)):
        raise ValueError('لا يمكن تغيير المفتاح بوجود أوامر أو مراكز معلقة — أغلقها أولًا')
    user['flow']={'type':'binance_easy','step':'key','full_mode':bool(full_mode),'key':'','started':time.time(),'custom_capital':0,'custom_max':0}
    B.save_state()
    if full_mode:
        B.send_msg(uid,
            '⚡ <b>إضافة سهلة مباشرة — وضع كامل الرصيد التراكمي 💎</b>\n\n'
            '1️⃣ أرسل <b>API Key</b> الآن كرسالة عادية هنا في الخاص\n'
            '• سيتم حذفه تلقائياً بعد ثوانٍ وتشفيره فوراً\n'
            '• لا ترسله في مجموعة\n'
            '• المفتاح يجب أن يكون Spot فقط بلا سحب\n\n'
            '⏱️ المهلة 5 دقائق — اكتب /cancel للإلغاء',
            [[B.bt('❌ إلغاء','api:easy_cancel')]])
    else:
        B.send_msg(uid,
            '🛠️ <b>إضافة سهلة مخصصة</b>\n\n'
            '1️⃣ أرسل <b>API Key</b> الآن\n'
            '• سيتم حذفه تلقائياً بعد الحفظ\n'
            '⏱️ المهلة 5 دقائق — /cancel للإلغاء',
            [[B.bt('❌ إلغاء','api:easy_cancel')]])

def handle_easy_text(uid, text, msg_id=None, user_obj=None):
    """معالجة رسائل التدفق السهل — تُستدعى من TITAN_UNIFIED_BOT handle_text_message"""
    st=B.load_state()
    u=st['users'].get(str(uid))
    if not u or not u.get('flow') or u['flow'].get('type')!='binance_easy':
        return False
    flow=u['flow']
    # تحقق مهلة
    if time.time()-flow.get('started',0)>EASY_TIMEOUT:
        u['flow']=None
        B.save_state()
        B.send_msg(uid,'⏰ انتهت مهلة إدخال المفتاح (5د). ابدأ من جديد.', B.back_kb([[B.bt('ربط binance','api:easy_full')]]))
        return True

    step=flow.get('step')
    txt=text.strip()

    # إلغاء
    if txt.lower() in ('/cancel','cancel','إلغاء','❌'):
        u['flow']=None
        B.save_state()
        B.send_msg(uid,'❌ أُلغي إدخال المفتاح.', keyboard(u))
        # حاول حذف رسالة المستخدم
        try:
            if msg_id: B.tg('deleteMessage', chat_id=uid, message_id=msg_id)
        except Exception: pass
        return True

    try:
        if step=='key':
            if not (16<=len(txt)<=256):
                B.send_msg(uid,'⚠️ طول المفتاح غير صحيح (16-256). أعد الإرسال أو /cancel')
                return True
            # احفظ Key مؤقتاً
            flow['key']=txt
            flow['step']='secret'
            flow['started']=time.time()
            B.save_state()
            # حذف رسالة المفتاح فوراً
            try:
                if msg_id: B.tg('deleteMessage', chat_id=uid, message_id=msg_id)
            except Exception: pass
            B.send_msg(uid,
                '✅ تم استلام API Key وتشفيره مؤقتاً\n\n'
                '2️⃣ الآن أرسل <b>API Secret</b> كرسالة هنا\n'
                '• سيتم حذفه فوراً بعد التحقق\n'
                '• لا تشاركه مع أحد',
                [[B.bt('❌ إلغاء','api:easy_cancel')]])
            return True

        elif step=='secret':
            if not (16<=len(txt)<=256):
                B.send_msg(uid,'⚠️ طول Secret غير صحيح. أعد الإرسال أو /cancel')
                return True
            secret=txt
            key=flow.get('key','')
            full_mode=flow.get('full_mode',True)
            # حذف رسالة Secret فوراً
            try:
                if msg_id: B.tg('deleteMessage', chat_id=uid, message_id=msg_id)
            except Exception: pass

            if full_mode:
                # وضع كامل الرصيد: capital=0 max_order=0
                try:
                    EXEC.connect(uid, key, secret, 0, 0, use_full_balance=True)
                    u['flow']=None
                    B.save_state()
                    B.send_msg(uid,
                        '✅ <b>تم الربط بنجاح — وضع كامل الرصيد التراكمي 💎</b>\n\n'
                        '🔐 المفتاح مشفّر بـ AESGCM ومحفوظ في /var/data\n'
                        '💎 سيستخدم كل رصيدك + ما تضيفه ويكمل بالمتبقي عند السحب — تراكمي\n'
                        '⚠️ رسائل المفتاح حُذفت تلقائياً\n\n'
                        'التداول لم يبدأ بعد — فعّله من الزر ⚡ التداول الحقيقي',
                        keyboard(u))
                except Exception as e:
                    u['flow']=None
                    B.save_state()
                    err=str(e) if isinstance(e,(ValueError,RuntimeError)) or e.__class__.__name__=='ExchangeError' else type(e).__name__
                    B.send_msg(uid,'⚠️ فشل الربط: '+B.esc(err), keyboard(u))
                return True
            else:
                # مخصص — انتقل لطلب capital
                flow['secret']=secret
                flow['step']='capital'
                B.save_state()
                B.send_msg(uid,
                    '✅ تم استلام Secret\n\n'
                    '3️⃣ أرسل <b>رأس المال المخصص</b> USDT — اكتب رقم مثل 400\n'
                    '• اكتب 0 لوضع كامل الرصيد التراكمي\n'
                    '• 50-100000',
                    [[B.bt('0 = كامل الرصيد 💎','api:easy_cap_0')],[B.bt('❌ إلغاء','api:easy_cancel')]])
                return True

        elif step=='capital' or step=='max_order':
            # تم إزالة الربط المخصص حسب طلب المستخدم - فقط وضع كامل الرصيد التراكمي
            B.send_msg(uid,
                '💎 <b>وضع كامل الرصيد التراكمي فقط</b>\n\n'
                'تم إزالة الربط المخصص حسب التحديث الجديد.\n'
                'سيتم استخدام كامل رصيدك بشكل تراكمي.\n\n'
                'اكتب /cancel للإلغاء وابدأ من جديد بزر ربط binance.',
                [[B.bt('❌ إلغاء','api:easy_cancel')]])
            return True

    except Exception as e:
        B.log(f'[EASY] {type(e).__name__}: {e}')
        try:
            if msg_id: B.tg('deleteMessage', chat_id=uid, message_id=msg_id)
        except Exception: pass
        u['flow']=None
        B.save_state()
        B.send_msg(uid,'⚠️ خطأ في الإدخال — أعد المحاولة', keyboard(u))
        return True

    return False

def callback(cb,u):
    global B
    data=cb.get('data','')
    if not data.startswith('api:') and data!='m:api':return False
    uid=u['id'];chat=(cb.get('message') or {}).get('chat',{})
    actor=(cb.get('from') or {}).get('id')
    if B is None:
        try:
            import sys
            B = sys.modules.get('TITAN_UNIFIED_BOT') or sys.modules.get('__main__')
        except Exception: pass
    if EXEC is None and B is not None:
        try:
            init(B)
        except Exception: pass
    if chat.get('type') not in (None,'private') or (actor is not None and int(actor)!=int(uid)):
        if B and hasattr(B, 'respond_cb'):
            B.respond_cb(cb,'🔒 ربط وتفعيل Binance متاحان في محادثة خاصة مع البوت فقط.')
        return True
    if EXEC is None:
        if B and hasattr(B, 'respond_cb'):
            B.respond_cb(cb,'⏳ طبقة Binance لم تجهز بعد.')
        return True
    try:
        if data=='api:add':
            B.respond_cb(cb,'🔐 استخدم الإضافة المباشرة في البوت عبر زر ربط binance - آمنة ومشفرة.',
                [[B.bt('ربط binance','api:easy_full')],
                 [B.bt('رجوع','m:api')]])
        elif data in ('api:easy','api:easy_full'):
            full = (data=='api:easy_full')
            # مسح flow قديم
            st=B.load_state()
            usr=st['users'].get(str(uid))
            if usr: usr['flow']=None
            B.save_state()
            start_easy_flow(uid, full_mode=full)
            B.respond_cb(cb,'⚡ بدأ الإدخال السهل المباشر — اتبع التعليمات في الرسائل التالية',[[B.bt('❌ إلغاء','api:easy_cancel')]])
        elif data=='api:easy_cancel':
            st=B.load_state()
            usr=st['users'].get(str(uid))
            if usr: usr['flow']=None
            B.save_state()
            B.respond_cb(cb,'❌ أُلغي إدخال المفتاح.',keyboard(u))
        elif data.startswith('api:easy_cap_') or data.startswith('api:easy_max_'):
            # تم إزالة الربط المخصص - فقط كامل الرصيد
            B.respond_cb(cb,'💎 وضع كامل الرصيد فقط - الربط المخصص تم إزالته',keyboard(u))
        elif data=='api:full':
            a=account(uid)
            if not a.get('credential'):raise ValueError('اربط المفتاح أولًا ثم فعّل وضع كامل الرصيد')
            if EXEC.active(a) or STORE.unresolved(uid):raise ValueError('أغلق المراكز أولًا قبل التبديل لوضع كامل الرصيد')
            a.update(use_full_balance=True, capital=0, max_order=0)
            STORE.save(a)
            B.respond_cb(cb,'💎 تم تفعيل وضع كامل الرصيد التراكمي ✅\n'+panel(u),keyboard(u))
        elif data=='api:real':
            a=account(uid)
            if not a.get('credential'):raise ValueError('اربط المفتاح أولًا')
            if not EXEC.allow_live:raise ValueError('التنفيذ العام مغلق؛ المشرف يضبط ALLOW_LIVE_TRADING=1 بعد الاختبار')
            token=secrets.token_hex(12);CONFIRMS[(str(uid),'enable')]=(token,time.time()+180)
            venue='أموال حقيقية' if STORE.venue=='live' else 'أموال Testnet تجريبية'
            mode = "كامل الرصيد التراكمي 💎" if a.get('use_full_balance') else f"{a['capital']:g} USDT"
            B.respond_cb(cb,f'⚠️ <b>تأكيد التداول الآلي — {venue}</b>\n'
                f'وضع الرصيد: {mode}، سقف الصفقة {a["max_order"]:g} (0=بدون سقف)، '
                f'خطر الوقف الاسمي بحد {a["max_risk_pct"]:g}%، حد تغير سعر الدخول/المطاردة {a["max_slippage_pct"]:g}%.\n'
                'بعد الموافقة يستطيع البوت الشراء والبيع تلقائيًا دون سؤال لكل صفقة. '
                'هل توافق؟',
                [[B.bt('✅ أوافق — فعّل','api:enable:'+token)],[B.bt('❌ تراجع','m:api')]])
        elif data.startswith('api:enable:'):
            confirm(uid,'enable',data.split(':')[-1]);EXEC.enable(uid)
            B.respond_cb(cb,'✅ فُعّل التداول للإشارات الجديدة اللاحقة فقط — وضع تراكمي.\n'+panel(u),keyboard(u))
        elif data=='api:paper':
            EXEC.pause(uid);u['settings']['paper']=True;B.save_state()
            B.respond_cb(cb,'📝 توقفت المشتريات الجديدة. تبقى متابعة المراكز القائمة ووقفها فعّالة.\n'+panel(u),keyboard(u))
        elif data=='api:kill':
            token=secrets.token_hex(12);CONFIRMS[(str(uid),'kill')]=(token,time.time()+180)
            B.respond_cb(cb,'🛑 هل تؤكد إلغاء حدود شراء البوت وبيع مراكزه المتتبعة سوقيًا؟ '
                'لن يبيع أرصدتك الأخرى. لا يمكن ضمان الملء أو السعر.',
                [[B.bt('✅ أؤكد الإغلاق','api:close:'+token)],[B.bt('تراجع','m:api')]])
        elif data.startswith('api:close:'):
            confirm(uid,'kill',data.split(':')[-1]);EXEC.kill(uid)
            B.respond_cb(cb,'🛑 أُرسل طلب الطوارئ؛ راجع إشعارات التنفيذ وBinance للتأكد.',keyboard(u))
        elif data=='api:del':
            EXEC.disconnect(uid);B.respond_cb(cb,'🗑️ حُذف الربط بعد التأكد من عدم وجود مراكز نشطة.',keyboard(u))
        elif data=='api:bal':
            bals=EXEC.client(account(uid)).balances()
            pos_text = '\n'.join(f'{B.esc(s)}: {q}' for s,q in sorted(bals.items()) if q>0 and (q >= 0.0001 or s in ('USDT','BTC','ETH','BNB','SOL')))
            text = '💼 <b>الأرصدة الحرة على Binance</b>\n' + (pos_text if pos_text else '• لا توجد أرصدة حرة تفوق الصفر حالياً.')
            try:
                total_eq, free, used = EXEC.get_total_equity(account(uid), EXEC.client(account(uid)), cached_bals=bals)
                text+=f'\n\n📊 إجمالي تراكمي: {total_eq:.2f} USDT | حر: {free:.2f} | مستخدم: {used:.2f}'
            except Exception: pass
            B.respond_cb(cb,text[:3800],keyboard(u))
        elif data=='api:orders':
            a=account(uid)
            lines=['📂 <b>دفتر التنفيذ الفعلي للبوت — v241 سهل+تراكمي</b>']
            for p in EXEC.active(a):
                lines.append(B.esc(f'{p["symbol"]} | {p["state"]} | qty={p["qty"]} | stop={p["stop"]} | budget={p.get("budget","?")} | equity_at_entry={p.get("total_equity_at_entry","?")}'))
            for o in STORE.unresolved(uid):lines.append(B.esc(f'غير مؤكد: {o["symbol"]} | {o["cid"]}'))
            B.respond_cb(cb,'\n'.join(lines) if len(lines)>1 else 'لا مراكز/أوامر نشطة للبوت.',keyboard(u))
        else:B.respond_cb(cb,panel(u),keyboard(u))
    except Exception as e:
        text=str(e) if isinstance(e,(ValueError,RuntimeError)) or e.__class__.__name__=='ExchangeError' else type(e).__name__
        B.respond_cb(cb,'⚠️ '+B.esc(text),keyboard(u))
    return True

def confirm(uid,action,token):
    item=CONFIRMS.pop((str(uid),action),None)
    if not item or item[1]<time.time() or not secrets.compare_digest(item[0],token):
        raise ValueError('التأكيد منتهي/غير صالح؛ افتح زر التفعيل أو الطوارئ مجددًا')

def on_cycle(res,baseline=False):
    if EXEC is None:return
    now=time.time()
    plans=[]
    for e in res.get('entry_plans',[]):
        p=dict(e);p['timestamp']=float(B.pd.Timestamp(e['time']).timestamp())
        if not baseline and 0<=now-p['timestamp']<=180:
            p['id']=hashlib.sha256(f'v102|{p["pool"]}|{p["ticker"]}|{p["timestamp"]}|{p["intent"]}'.encode()).hexdigest()[:24]
            plans.append(p)
    for uid,u in list(B.load_state()['users'].items()):
        if not u['settings'].get('signals',True) or not B.is_allowed(int(uid),u.get('username')):continue
        for p in plans:
            if p['intent']=='LIMIT':
                msg=B.fmt_entry(p,res['w2_current'],res.get('holds')).replace('صفقة متوسطة المدى','أمر شراء مشروط')
                STORE.notify(uid,'waiting:'+p['id'],msg+'\n⏳ إشارة انتظار حد شراء؛ ليست عملية منفذة. المهلة 12 ساعة، وتطبق حدود المطاردة للحساب الحقيقي.')
    for a in STORE.accounts():
        uid=a['uid']
        if not B.is_allowed(int(uid)):
            EXEC.pause(uid)
        active=EXEC.active(a)
        cutoff=min((p['source_time'] for p in active),default=now)
        for e in res.get('events',[]):
            if e['kind']=='ENTRY':continue
            stamp=float(B.pd.Timestamp(e['time']).timestamp())
            if stamp<=cutoff or stamp>now:continue
            EXEC.on_exit(uid,dict(e,timestamp=stamp))
        for p in plans:
            if not B.is_allowed(int(uid)):continue
            try:EXEC.accept_plan(uid,p,now)
            except Exception as e:
                msg=str(e) if isinstance(e,ValueError) or e.__class__.__name__=='ExchangeError' else type(e).__name__
                STORE.notify(uid,'skipped:'+p['id'],'⏭️ لم يُنفّذ شراء '+p['ticker']+': '+B.esc(msg))
        snaps=[]
        for s in res.get('open_positions',[]):
            if s.get('opened'):snaps.append(dict(s,opened_ts=float(B.pd.Timestamp(s['opened']).timestamp())))
        EXEC.update_stops(uid,snaps)


# Minimal SetupMixin - page linking removed, only direct bot linking
class SetupMixin:
    def setup_reply(self,body,status=200,nonce=None):
        try:
            payload=body.encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type','text/html; charset=utf-8')
            self.send_header('Content-Length',str(len(payload)))
            self.send_header('Cache-Control','no-store')
            self.end_headers()
            self.wfile.write(payload)
        except:
            pass
    def do_POST(self):
        self._send(b"Page linking removed - use direct bot linking", 410)
    def do_GET(self):
        if self.path=='/connect':
            self._send(b"Page linking removed - use direct bot linking via bot button", 410)
            return
        return super().do_GET()
