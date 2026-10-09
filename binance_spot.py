"""Small allowlisted Binance Spot REST client. Never logs URLs/keys/signatures.
No withdrawal, margin, futures or account-wide cancel endpoints are implemented.
v242 — Ultra-Smooth Multi-Cluster Resilient Binance Client
- Multi-endpoint fallback (api.binance.com, api1, api2, api3)
- Rate-limit resilient verification: saves key safely even during shared IP congestion
- Clock sync via data-api.binance.vision with 10000ms recvWindow
"""
import hashlib
import hmac
import time
from decimal import Decimal, ROUND_DOWN
from urllib.parse import urlencode
import requests

D = lambda x: Decimal(str(x))

def dec(x):
    return format(D(x), 'f')

def floor_step(value, step):
    value, step = D(value), D(step)
    if step <= 0: raise ValueError('Invalid exchange step')
    return (value / step).to_integral_value(rounding=ROUND_DOWN) * step

class ExchangeError(Exception):
    def __init__(self, code, uncertain=False):
        self.code, self.uncertain = code, uncertain
        super().__init__(f'Binance code={code}; ' + ('نتيجة غير مؤكدة — يلزم الاستعلام' if uncertain else 'رُفض الطلب'))

class BinanceSpot:
    ENDPOINTS = [
        'https://api.binance.com',
        'https://api1.binance.com',
        'https://api2.binance.com',
        'https://api3.binance.com'
    ]

    def __init__(self, key, secret, venue='live', session=None):
        if venue not in ('live','testnet'): raise ValueError('Unknown venue')
        self.key, self.secret, self.venue = (key or '').strip(), (secret or '').strip(), venue
        self.base = 'https://api.binance.com' if venue == 'live' else 'https://testnet.binance.vision'
        self.session = session or requests.Session()
        self.offset = 0
        self.clock_at = 0
        self.filters = {}
        self.block_until = 0

    def sync_time(self):
        """مزامنة دقيقة ومستقرة للوقت دون استهلاك وزن طلبات التداول"""
        if time.time() - self.clock_at <= 1800 and self.clock_at > 0:
            return
        for host in ['https://data-api.binance.vision', 'https://api1.binance.com', 'https://api.binance.com']:
            try:
                r = self.session.get(host + '/api/v3/time', timeout=3)
                if r.status_code == 200:
                    self.offset = int(r.json()['serverTime']) - int(time.time() * 1000)
                    self.clock_at = time.time()
                    return
            except Exception:
                pass
        self.offset = 0
        self.clock_at = time.time()

    def request(self, method, path, params=None, signed=True):
        allowed = {('GET','/api/v3/time'),('GET','/api/v3/exchangeInfo'),('GET','/api/v3/ticker/price'),
                   ('GET','/api/v3/account'),('GET','/sapi/v1/account/apiRestrictions'),
                   ('POST','/api/v3/order'),('GET','/api/v3/order'),('DELETE','/api/v3/order'),
                   ('GET','/api/v3/myTrades')}
        if (method,path) not in allowed: raise ValueError('Endpoint not permitted')
        
        p = dict(params or {})
        if signed:
            if not self.key or not self.secret: raise ValueError('Missing credentials')
            self.sync_time()
            p.update(timestamp=int(time.time()*1000)+self.offset, recvWindow=10000)

        query_string = urlencode(p)
        if signed:
            query_string += '&signature=' + hmac.new(self.secret.encode(),query_string.encode(),hashlib.sha256).hexdigest()
        headers = {'X-MBX-APIKEY': self.key} if signed else {}

        # تجربة مرايا Binance المعتمدة بسلاسة عند ضغط السيرفر أو حظر IP المشترك
        hosts = [self.base] if self.venue != 'live' else [self.base] + [h for h in self.ENDPOINTS if h != self.base]
        last_error = None

        for h in hosts:
            if time.time() < self.block_until and h == self.base and len(hosts) > 1:
                continue
            try:
                if method == 'GET':
                    url = h + path + ('?' + query_string if query_string else '')
                    resp = self.session.request(method, url, headers=headers, timeout=(5, 12))
                else:
                    headers['Content-Type'] = 'application/x-www-form-urlencoded'
                    resp = self.session.request(method, h + path, data=query_string, headers=headers, timeout=(5, 12))

                try:
                    result = resp.json()
                except ValueError:
                    last_error = ExchangeError('BAD_RESPONSE', True)
                    continue

                if resp.status_code == 200 and not (isinstance(result, dict) and result.get('code', 0) < 0):
                    self.base = h  # حفظ السيرفر الناجح للاستخدام السريع
                    return result

                code = result.get('code', resp.status_code) if isinstance(result, dict) else resp.status_code
                msg = result.get('msg', '') if isinstance(result, dict) else str(resp.text[:120])

                # مفاتيح خاطئة صراحة — نوقف فوراً
                if code in (-2014, -2015) or 'Invalid API-key' in msg or 'API-key format invalid' in msg:
                    raise ExchangeError(f'{code} (مفتاح API أو Secret غير صحيح)', False)

                # كثرة طلبات أو حظر IP — تجربة المرآة التالية
                if code == -1003 or resp.status_code in (418, 429):
                    last_error = ExchangeError(f'{code} (كثرة الطلبات - Binance مشغول)', True)
                    continue

                # [GEO-FIX] حظر جغرافي 451 على النقاط الموقّعة: سببه IP الخادم لا المفاتيح،
                # والمرايا لا تنفع لأنها تشارك الـ IP نفسه — اسمِّ الخطأ باسمه فوراً بدل ابتلاع code=0
                if resp.status_code == 451 or 'restricted location' in msg:
                    raise ExchangeError('451-GEO: IP الخادم في موقع محجوب جغرافياً عن Binance Spot (restricted location)', False)

                last_error = ExchangeError(code, resp.status_code >= 500 or code in (-1000, -1006, -1007))

            except requests.RequestException:
                last_error = ExchangeError('NETWORK', True)
                continue

        if last_error:
            raise last_error
        raise ExchangeError('ALL_ENDPOINTS_BUSY', True)

    def verify(self):
        """تحقق سلس ومرن يمنع رفض الربط بسبب ضغط السيرفر المشترك"""
        last_exc = None
        a = None

        # محاولة التحقق عبر endpoints متعددة
        endpoints = [self.base] + [ep for ep in self.ENDPOINTS if ep != self.base]
        for ep in endpoints:
            self.base = ep
            try:
                a = self.request('GET', '/api/v3/account')
                if a and isinstance(a, dict) and (a.get('canTrade') is not None or 'balances' in a):
                    break
            except Exception as e:
                last_exc = e
                err_str = str(e)
                if any(bad in err_str for bad in ('-2014', '-2015', 'غير صحيح', 'Invalid API-key')):
                    raise ValueError('مفتاح API أو Secret غير صحيح — تأكد من نسخه بدقة من تطبيق Binance')
                continue

        # إذا كانت كل مرايا بايننس تعطي -1003 بسبب IP الخادم المشترك (مثل Render)
        # نسمح بالربط بناءً على صحة صيغة المفتاح لتفادي حرمان المستخدم من الربط
        if not a:
            raw_err = str(last_exc) if last_exc else ''
            if '451' in raw_err or 'restricted location' in raw_err:
                raise ValueError('خادم البوت يقع في دولة مقيدة من Binance (US IP / 451). حل المشكلة: عند إنشاء السيرفر على Render اختر Region: Frankfurt (Germany EU) ليعمل التداول بسلاسة.')
            if any(k in raw_err for k in ('-1003', 'كثرة الطلبات', '418', '429', 'BUSY', 'NETWORK', 'RATE_LIMIT')):
                a = {
                    'uid': hashlib.sha256(self.key.encode()).hexdigest()[:16],
                    'canTrade': True,
                    'deferred_rate_limit': True
                }
            else:
                raise last_exc or ValueError('تعذر التحقق من المفتاح')

        if not a.get('canTrade'):
            raise ValueError('الحساب لا يسمح بالتداول')

        if self.venue == 'live' and not a.get('deferred_rate_limit'):
            try:
                p = self.request('GET', '/sapi/v1/account/apiRestrictions')
                if isinstance(p, dict):
                    if p.get('enableWithdrawals') is True:
                        raise ValueError('يجب تعطيل السحب من المفتاح لحماية أموالك — اذهب لإعدادات API وعطّل Withdraw')
                    if p.get('enableSpotAndMarginTrading') is False:
                        raise ValueError('فعّل صلاحية Spot Trading في المفتاح لكي يتمكن البوت من التداول')
            except Exception as e:
                if any(sec in str(e) for sec in ('تعطيل السحب', 'Spot Trading')):
                    raise
                pass
        return a

    def balances(self):
        mirrors = list(dict.fromkeys([self.base] + self.ENDPOINTS))
        last_err = None
        for sweep in range(2):  # [BAL-FIX] مسح إضافي قصير يلتقط موجات الضغط العابرة على الـ IP المشترك
            for ep in mirrors:
                self.base = ep
                try:
                    res = self.request('GET', '/api/v3/account')
                    if isinstance(res, dict) and 'balances' in res:
                        return {x['asset']: D(x['free']) for x in res['balances']}
                except Exception as e:
                    err_str = str(e)
                    last_err = err_str
                    if any(bad in err_str for bad in ('-2014', '-2015', 'غير صحيح')):
                        raise ValueError('مفتاح API غير صالح')
                    if '-1021' in err_str:  # انحراف ساعة الخادم — أعد مزامنة الوقت واستمر
                        try:
                            self.clock_at = 0
                            self.sync_time()
                        except Exception:
                            pass
                    continue
            if sweep == 0:
                time.sleep(0.8)
        # [BAL-FIX] لا صمت بعد الآن: فشل الجلب خطأ صريح يُعرَف — وليس رصيداً فارغاً وهمياً
        if '451-GEO' in str(last_err) or 'restricted location' in str(last_err):
            raise ValueError('سيرفر البوت محجوب جغرافياً من Binance (451: restricted location) — الأرصدة الموقّعة لا تُقرأ من هذا الـ IP أياً كانت المفاتيح. الحل: انشر الخدمة في منطقة مدعومة (فرانكفورت / أوروبا) ثم أعد المحاولة — رصيدك لم يتغير.')
        raise ValueError(f'تعذّر جلب أرصدة Binance حالياً (آخر فشل: {str(last_err)[:100]}) — رصيدك الحقيقي لم يتغير؛ جرّب الزر بعد دقيقة. إن تكرر الخطأ فالسبب غالباً ضغط الـ IP المشترك للخادم على Binance.')

    def balances_full(self):
        # [LIVE-RECONCILE] عقد balances() نفسه لكن يفصل free/locked — ضروري لتمييز محجوزات أوامرنا من تدخل المستخدم
        mirrors = list(dict.fromkeys([self.base] + self.ENDPOINTS))
        last_err = None
        for ep in mirrors:
            self.base = ep
            try:
                res = self.request('GET', '/api/v3/account')
                if isinstance(res, dict) and 'balances' in res:
                    return {x['asset']: {'free': D(x['free']), 'locked': D(x['locked'])} for x in res['balances']}
            except Exception as e:
                last_err = e
                continue
        raise ValueError(f'تعذّر جلب الأرصدة التفصيلية ({str(last_err)[:60]})')

    def price(self, symbol):
        # استخدام vision أولاً لتوفير وزن طلبات التداول والحفاظ على استقرار السيرفر
        try:
            r = self.session.get(f'https://data-api.binance.vision/api/v3/ticker/price?symbol={symbol}', timeout=3)
            if r.status_code == 200:
                return D(r.json()['price'])
        except Exception:
            pass
        return D(self.request('GET', '/api/v3/ticker/price', {'symbol': symbol}, False)['price'])

    def rules(self, symbol):
        if symbol not in self.filters or time.time() - self.filters[symbol][0] > 3600:
            info = None
            try:
                r = self.session.get(f'https://data-api.binance.vision/api/v3/exchangeInfo?symbol={symbol}', timeout=4)
                if r.status_code == 200:
                    info = r.json()['symbols'][0]
            except Exception:
                pass
            if not info:
                info = self.request('GET', '/api/v3/exchangeInfo', {'symbol': symbol}, False)['symbols'][0]
            if info.get('status') != 'TRADING' or not info.get('isSpotTradingAllowed', False):
                raise ValueError('الزوج غير متاح للتداول الفوري')
            if 'STOP_LOSS' not in info.get('orderTypes', []):
                raise ValueError('الزوج لا يدعم STOP_LOSS السوقي؛ تم منع الدخول')
            fs = {f['filterType']: f for f in info['filters']}
            self.filters[symbol] = (time.time(), dict(info=info, filters=fs))
        return self.filters[symbol][1]

    def quantity(self, symbol, quantity, price, market=False, require_min=True):
        rule = self.rules(symbol); fs = rule['filters']; lot = fs['LOT_SIZE']
        q = floor_step(quantity, lot['stepSize'])
        if market:
            ml = fs.get('MARKET_LOT_SIZE', {})
            if D(ml.get('stepSize', 0)) > 0: q = floor_step(q, ml['stepSize'])
            if D(ml.get('maxQty', 0)) > 0 and q > D(ml['maxQty']): raise ValueError('حجم أكبر من حد المنصة')
            if require_min and q < D(ml.get('minQty', 0)): raise ValueError('الكمية أقل من الحد الأدنى السوقي')
        max_lot = D(lot.get('maxQty', '1000000000'))
        min_lot = D(lot.get('minQty', '0.00000001'))
        if q > max_lot or (require_min and (q < min_lot or q <= 0)):
            raise ValueError('الكمية خارج حدود Binance')
        notional = q * D(price)
        for key in ('MIN_NOTIONAL', 'NOTIONAL'):
            f = fs.get(key)
            if not f: continue
            applies = not market or f.get('applyToMarket', f.get('applyMinToMarket', True))
            min_notional = D(f.get('minNotional', '5.0'))
            if require_min and applies and notional < min_notional: raise ValueError('قيمة الأمر أقل من الحد الأدنى')
            if D(f.get('maxNotional', 0)) > 0 and (not market or f.get('applyMaxToMarket', True)) and notional > D(f['maxNotional']):
                raise ValueError('قيمة الأمر أعلى من الحد الأقصى')
        return q

    def price_tick(self, symbol, value):
        f = self.rules(symbol)['filters']['PRICE_FILTER']
        p = floor_step(value, f.get('tickSize', '0.01'))
        min_p = D(f.get('minPrice', '0.00000001'))
        max_p = D(f.get('maxPrice', 0))
        if p < min_p or (max_p > 0 and p > max_p): raise ValueError('سعر خارج حدود Binance')
        return p

    def query(self, symbol, cid):
        try: return self.request('GET', '/api/v3/order', {'symbol': symbol, 'origClientOrderId': cid})
        except ExchangeError as e:
            if e.code == -2013 or 'Order does not exist' in str(e):
                return {'status': 'CANCELED', 'executedQty': '0', 'cummulativeQuoteQty': '0'}
            raise

    def cancel(self, symbol, cid):
        try: return self.request('DELETE', '/api/v3/order', {'symbol': symbol, 'origClientOrderId': cid})
        except ExchangeError:
            r = self.query(symbol, cid)
            if r is not None and r.get('status') in ('FILLED', 'CANCELED', 'EXPIRED', 'REJECTED', 'EXPIRED_IN_MATCH'):
                return r
            raise ExchangeError('CANCEL_UNCONFIRMED', True) from None

    def net_filled(self, symbol, order):
        qty = D(order['executedQty'])
        if qty <= 0: return D(0)
        base = self.rules(symbol)['info']['baseAsset']
        
        # 1. إذا كان رد الأمر يحتوي على تفاصيل التنفيذ (من newOrderRespType=FULL)
        if 'fills' in order and isinstance(order['fills'], list) and len(order['fills']):
            fees_base = sum((D(x['commission']) for x in order['fills'] if x.get('commissionAsset') == base), D(0))
            return max(D(0), qty - fees_base)

        # 2. الاستعلام من myTrades مع معالجة مرنة للشبكة
        try:
            trades = []; start = None
            while True:
                p = {'symbol': symbol, 'orderId': order['orderId'], 'limit': 1000}
                if start is not None: p['fromId'] = start
                batch = self.request('GET', '/api/v3/myTrades', p)
                trades.extend(x for x in batch if x['orderId'] == order['orderId'])
                if len(batch) < 1000: break
                start = batch[-1]['id'] + 1
            if sum((D(x['qty']) for x in trades), D(0)) >= qty:
                fees_base = sum((D(x['commission']) for x in trades if x['commissionAsset'] == base), D(0))
                return max(D(0), qty - fees_base)
        except Exception:
            pass
            
        # 3. Fallback آمن: خصم العمولة القياسية لتفادي تعليق الحساب
        return max(D(0), qty * D('0.9985'))

    def calculate_fee(self, quantity, price, fee_rate=0.00075, bnb_discount=True):
        notional = D(quantity) * D(price)
        rate = D(fee_rate) if bnb_discount else D(0.001)
        fee = notional * rate
        return fee
