"""Spot execution adapter — v240 CUMULATIVE — يستخدم كامل الرصيد تراكمياً
Fresh plans only. GTC limits are submitted at decision time, never retrospectively.
Orders use a durable intent ledger; an uncertain POST is queried, never blindly repeated.
v240 CUMULATIVE: يدعم وضع كامل الرصيد — يستخدم كل ما تضيفه ويكمل بالمتبقي عند السحب — تراكمي
"""
import hashlib
import math
import time
import threading
from binance_spot import BinanceSpot,ExchangeError,D,dec

TERMINAL={'FILLED','CANCELED','EXPIRED','EXPIRED_IN_MATCH','REJECTED'}

class LiveExecutor:
    def __init__(self,store,params,allow_live=False,client_factory=None):
        self.store=store;self.params=params;self.allow_live=allow_live
        self.client_factory=client_factory;self.lock=threading.RLock();self.clients={}

    def client(self,a):
        if self.client_factory:return self.client_factory(a)
        blob=a.get('credential')
        if not blob:raise ValueError('اربط مفتاح Binance أولًا')
        ident=(a['uid'],blob)
        if ident not in self.clients:
            keys=self.store.decrypt(a['uid'],blob)
            self.clients[ident]=BinanceSpot(keys['key'],keys['secret'],self.store.venue)
        return self.clients[ident]

    def active(self,a):return [p for p in a['positions'].values() if p['state'] not in ('CLOSED','SKIPPED')]

    def get_total_equity(self, a, client, cached_bals=None):
        """حساب إجمالي الرصيد التراكمي — الرصيد الحر + قيمة المراكز المفتوحة"""
        try:
            if cached_bals is not None and isinstance(cached_bals, dict):
                raw = cached_bals.get('USDT', D(0))
            else:
                raw = client.balances().get('USDT', D(0))
            if isinstance(raw, dict):
                free_usdt = D(str(raw.get('free', 0)))
            else:
                free_usdt = D(str(raw))
        except:
            free_usdt = D(0)
        used = sum(D(p['budget']) for p in self.active(a))
        # في وضع كامل الرصيد: total = free + used (كل ما في الحساب المخصص للبوت)
        # في الوضع العادي: total = capital
        if a.get('use_full_balance') or D(a.get('capital',0))==0:
            return free_usdt + used, free_usdt, used
        else:
            return D(a['capital']), free_usdt, used

    def connect(self,uid,key,secret,capital,max_order,use_full_balance=False):
        with self.lock:
            if not (len(key)>=16 and len(secret)>=16 and len(key)<=256 and len(secret)<=256):raise ValueError('صيغة المفتاح غير صحيحة')
            # v240: السماح بـ capital=0 يعني كامل الرصيد تراكمي
            capital_f=float(capital)
            max_order_f=float(max_order)
            if not all(math.isfinite(x) for x in (capital_f,max_order_f)):
                raise ValueError('قيم رأس المال غير صالحة')
            if use_full_balance or capital_f==0:
                # وضع كامل الرصيد: capital=0 يعني ديناميكي، max_order يمكن أن يكون 0 يعني بدون سقف
                if not (0<=capital_f<=100000 and 0<=max_order_f<=100000):
                    raise ValueError('في وضع كامل الرصيد: رأس المال 0 = ديناميكي، سقف الصفقة 0 = بدون سقف، أو قيمة محددة')
            else:
                if not (50<=capital_f<=100000 and 10<=max_order_f<=capital_f):
                    raise ValueError('رأس المال 50–100000 USDT، وحد الصفقة بين 10 ورأس المال')
            a=self.store.account(uid)
            if self.active(a) or self.store.unresolved(uid):raise ValueError('لا يمكن تغيير المفتاح بوجود أوامر أو مراكز معلقة')
            client=BinanceSpot(key,secret,self.store.venue) if not self.client_factory else self.client_factory(a)
            info=client.verify()
            fingerprint=hashlib.sha256(key.encode()).hexdigest()
            exchange_uid=str(info.get('uid',''))
            for other in self.store.accounts():
                if other['uid']!=str(uid) and (other.get('key_fingerprint')==fingerprint or (exchange_uid and other.get('exchange_uid')==exchange_uid)):
                    raise ValueError('هذا الحساب مربوط بمستخدم آخر؛ لا تشارك نفس حساب التداول')
            a.update(credential=self.store.encrypt(uid,key,secret),key_fingerprint=fingerprint,
                     exchange_uid=exchange_uid,enabled=False,halt=None,capital=capital_f,max_order=max_order_f,
                     use_full_balance=bool(use_full_balance or capital_f==0),
                     connected_at=time.time())
            self.store.save(a)
            if a.get('use_full_balance'):
                self.store.notify(uid,'connected:'+str(int(time.time())),
                    '🔑 تم ربط Binance بنجاح — وضع كامل الرصيد التراكمي مفعّل ✅\n'
                    'البوت سيستخدم كل رصيدك الحر + قيمة مراكزه — عند الإضافة يستخدم الزيادة، وعند السحب يكمل بالمتبقي — تراكمي.\n'
                    'التداول الآلي لم يُفعّل بعد؛ فعّله صراحة من قائمة البوت.')
            else:
                self.store.notify(uid,'connected:'+str(int(time.time())),
                    '🔑 تم ربط Binance بنجاح. التداول الآلي لم يُفعّل بعد؛ فعّله صراحة من قائمة البوت بعد مراجعة رأس المال.')

    def enable(self,uid):
        with self.lock:
            a=self.store.account(uid)
            if not self.allow_live:raise ValueError('التفعيل العام مغلق: يضبط المشرف ALLOW_LIVE_TRADING=1 بعد الاختبار')
            if self.store.unresolved(uid):raise ValueError('يوجد أمر غير مؤكد؛ راجعه على Binance ولا تعاود إرساله')
            if any(p['state']=='MANUAL' for p in self.active(a)):raise ValueError('يوجد مركز يتطلب مراجعة يدوية')
            self.client(a).verify()
            a.update(enabled=True,activated_at=time.time(),halt=None)
            self.store.save(a)

    def pause(self,uid):
        with self.lock:
            a=self.store.account(uid);a['enabled']=False;self.store.save(a)

    def disconnect(self,uid):
        with self.lock:
            a=self.store.account(uid)
            if self.active(a) or self.store.unresolved(uid):raise ValueError('أغلق/سوِّ مراكز البوت أولًا؛ لا تُحذف مفاتيح مركز مفتوح')
            a.update(credential=None,enabled=False,use_full_balance=False);self.store.save(a)
            self.clients={k:v for k,v in self.clients.items() if k[0]!=str(uid)}

    def cid(self,uid,pid,action):
        return 'tt4_'+hashlib.sha256(f'{uid}|{pid}|{action}|{self.store.venue}'.encode()).hexdigest()[:28]

    def order(self,a,client,cid,params):
        existing=self.store.order(a['uid'],cid)
        if existing:
            if existing['state']=='REJECTED':raise ExchangeError('PREVIOUSLY_REJECTED')
            response=client.query(params['symbol'],cid)
            if response is None:
                self.store.order_result(a['uid'],cid,'UNKNOWN')
                raise ExchangeError('ORDER_NOT_RESOLVED',True)
            self.store.order_result(a['uid'],cid,'ACK',response)
            return response
        params=dict(params,newClientOrderId=cid,newOrderRespType='FULL')
        self.store.prepare(a['uid'],cid,params)
        try:
            response=client.request('POST','/api/v3/order',params)
            self.store.order_result(a['uid'],cid,'ACK',response)
            try:
                from emergency_circuit_breaker import BREAKER
                BREAKER.record_api_success()
            except: pass
            return response
        except ExchangeError as e:
            self.store.order_result(a['uid'],cid,'UNKNOWN' if e.uncertain else 'REJECTED')
            try:
                from emergency_circuit_breaker import BREAKER
                BREAKER.record_api_error(str(e))
            except: pass
            raise

    def query_known(self,a,client,cid,symbol):
        response=client.query(symbol,cid)
        if response is None:raise ExchangeError('ORDER_NOT_RESOLVED',True)
        self.store.order_result(a['uid'],cid,'ACK',response)
        return response

    def fault(self,a,p,error):
        code=str(error) if isinstance(error,(ExchangeError,ValueError)) else type(error).__name__
        a['enabled']=False;a['halt']=code
        self.store.save(a)
        self.store.notify(a['uid'],'fault:'+p.get('id','account')+':'+code,
            '⚠️ أُوقف فتح صفقات جديدة. '+code+'\nراقب أوامر ومراكز Binance؛ المتابعة تحاول تسوية الأوامر القائمة. لا يوجد ضمان للتنفيذ أثناء تعطل الشبكة.')

    def accept_plan(self,uid,plan,now=None):
        try:
            from emergency_circuit_breaker import BREAKER
            can_open, b_reason = BREAKER.can_open_new_trade()
            if not can_open:
                return None
        except: pass
        now=time.time() if now is None else now
        with self.lock:
            a=self.store.account(uid)
            if plan['intent'] not in ('MARKET','LIMIT') or plan['pool'] not in self.params:
                raise ValueError('نوع خطة دخول غير صالح')
            if not all(math.isfinite(float(plan[k])) and float(plan[k])>0 for k in ('timestamp','price','signal_price','sl','tgt1','tgt2','size_pct')):
                raise ValueError('قيم خطة الدخول غير صالحة')
            stamp=float(plan['timestamp'])
            if not a['enabled'] or not self.allow_live or a.get('halt'):return False
            if not (0<=now-stamp<=180) or stamp<a['activated_at']:return False
            if plan['id'] in a['positions']:return False
            if self.store.unresolved(uid):return False
            c=self.client(a);symbol=plan['ticker'];pp=self.params[plan['pool']]
            price=c.price(symbol);ref=D(plan['signal_price']);target=D(plan['price'])
            
            # السماح بعدة صفقات لنفس العملة مع منع التكرار عند نفس السعر (فارق 1% على الأقل)
            same_sym_positions = [p for p in self.active(a) if p['symbol'] == symbol]
            if len(same_sym_positions) >= 3: return False
            if any(abs(D(p.get('entry_price', price)) / price - 1) < D('0.01') for p in same_sym_positions):
                return False

            slip=D(a.get('max_slippage_pct', 1.0))/100
            if plan['intent']=='MARKET' and abs(price/ref-1)>slip:return False
            if price<=D(plan['sl']):return False
            base=price if plan['intent']=='MARKET' else target
            
            # v240 CUMULATIVE LOGIC — يستخدم كامل الرصيد تراكمياً
            total_equity, free_usdt, used = self.get_total_equity(a, c)
            stop_ratio=(base-D(plan['sl']))/base
            if stop_ratio<=0:return False
            
            if a.get('use_full_balance') or D(a.get('capital',0))==0:
                # وضع كامل الرصيد التراكمي
                remaining = free_usdt
                budget = total_equity * D(plan['size_pct'])/100
                max_order_val = D(a.get('max_order', 0))
                if max_order_val > 0:
                    budget = min(budget, max_order_val)
                budget = min(budget, remaining * D('0.99'), free_usdt * D('0.99'))
                risk_cap = total_equity * D(a.get('max_risk_pct', 2.0))/100 / stop_ratio
                budget = min(budget, risk_cap)
            else:
                # الوضع القديم — رأس مال ثابت
                remaining=max(D(0),D(a.get('capital', 100))-used)
                budget=min(D(a.get('capital', 100))*D(plan['size_pct'])/100,D(a.get('max_order', 25)),remaining,
                           free_usdt*D('.99'))
                budget=min(budget,D(a.get('capital', 100))*D(a.get('max_risk_pct', 2.0))/100/stop_ratio)
            
            # حد أدنى لتفادي فشل أوامر الأهداف المجزأة 50% مع عمولات بايننس
            if budget < D('11.5') and free_usdt >= D('12.0'):
                budget = D('12.0')
            if budget < D('11.0'):
                return False
            
            qty=c.quantity(symbol,budget*D('.998')/base,base,plan['intent']=='MARKET')
            net=qty*D('.998')
            t1=net*D(pp['t1_frac']);t2=(net-t1)*D(pp['t2_frac_of_rest'])
            c.quantity(symbol,t1,plan['tgt1'],True)
            c.quantity(symbol,t2,plan['tgt2'],True)
            if (net - t1 - t2) > 0:
                c.quantity(symbol,net-t1-t2,plan['sl'],True)
            stop=c.price_tick(symbol,plan['sl'])
            if stop>=price:raise ValueError('الوقف لم يعد أدنى سعر السوق')
            pid=plan['id'];cid=self.cid(uid,pid,'buy')
            params={'symbol':symbol,'side':'BUY','type':plan['intent'],'quantity':dec(qty)}
            if plan['intent']=='LIMIT':params.update(price=dec(c.price_tick(symbol,target)),timeInForce='GTC')
            p={'id':pid,'symbol':symbol,'pool':plan['pool'],'state':'PENDING','plan':dict(plan),
               'source_time':stamp,'budget':dec(budget),'buy_cid':cid,'buy_params':params,
               'created':now,'expires':stamp+600,'stop':dec(stop),'qty':'0','original_qty':'0',
               'stop_cid':None,'stop_revision':0,'exit':None,'stage':0,'chased':False,
               'total_equity_at_entry':dec(total_equity), 'free_at_entry':dec(free_usdt)}
            a['positions'][pid]=p;self.store.save(a)
            try:
                self.order(a,c,cid,params)
                mode_text = "كامل الرصيد التراكمي" if a.get('use_full_balance') else "ثابت"
                self.store.notify(uid,pid+':submitted',
                    f'📨 أُرسل أمر شراء {symbol} — {plan["intent"]} — وضع {mode_text}.\n'
                    f'إجمالي الرصيد التراكمي {total_equity:.2f} USDT | الحر {free_usdt:.2f} | المستخدم {used:.2f} | حد الإنفاق لهذه الخطة {budget:.2f} USDT.\n'
                    f'لا يُعد شراءً منفذًا حتى تأكيد Binance.')
                self._poll_position(a,c,p,now)
            except Exception as e:
                p['state']='SKIPPED';self.store.save(a)
                err_code = str(e)
                if any(bad in err_code for bad in ('-2014', '-2015', 'Invalid API-key', 'IP restricted')):
                    self.fault(a,p,e)
                else:
                    self.store.notify(uid, pid+':buy_skipped', f'⚠️ تعذر شراء {symbol}: {err_code}\nالحساب لا يزال نشطاً وسيتابع الصفقات القادمة.')
            return True

    def _protect(self,a,c,p):
        if D(p['qty'])<=0:p['state']='CLOSED';self.store.save(a);return
        price=c.price(p['symbol']);stop=c.price_tick(p['symbol'],p['stop'])
        if stop>=price:
            return self._start_exit(a,c,p,'SAFETY',1.0)
        if not p.get('stop_cid'):
            p['stop_revision']+=1
            p['stop_cid']=self.cid(a['uid'],p['id'],'stop:'+str(p['stop_revision']))
            self.store.save(a)
        params={'symbol':p['symbol'],'side':'SELL','type':'STOP_LOSS',
                'quantity':dec(c.quantity(p['symbol'],p['qty'],stop,True)), 'stopPrice':dec(stop)}
        try:
            r=self.order(a,c,p['stop_cid'],params)
            p['stop_qty']=params['quantity'];self.store.save(a)
            if r['status']=='FILLED':
                p['qty']='0';p['state']='CLOSED';self.store.save(a)
            elif r['status'] in TERMINAL:
                raise ValueError('لم يقبل Binance أمر الحماية؛ راجع المركز')
        except ExchangeError as e:
            if not e.uncertain:
                p['stop_cid']=None;self.store.save(a)
                self._start_exit(a,c,p,'SAFETY',1.0)
            raise
        self.store.notify(a['uid'],p['id']+':protection:'+str(p['stop_revision']),
            f'🛡️ وقف خسارة سوقي على Binance لـ {p["symbol"]} عند {stop}. الانزلاق والفجوات ما زالا ممكنين.')

    def _cancel_stop(self,a,c,p):
        if not p.get('stop_cid'):return True
        r=self.query_known(a,c,p['stop_cid'],p['symbol'])
        if r['status'] not in TERMINAL:r=c.cancel(p['symbol'],p['stop_cid'])
        if r['status'] not in TERMINAL:raise ExchangeError('STOP_CANCEL_UNCONFIRMED',True)
        executed=D(r.get('executedQty',0))
        p['qty']=dec(max(D(0),D(p['qty'])-executed))
        if executed>0:
            self.store.notify(a['uid'],p['id']+':stop-fill:'+p['stop_cid'],
                f'🔴 Binance {p["symbol"]}: كمية منفذة من الوقف {executed}، الحالة {r["status"]}، الأمر {r["orderId"]}.')
        p['stop_cid']=None
        if D(p['qty'])<=0:p['state']='CLOSED'
        self.store.save(a)
        return p['state']!='CLOSED'

    def _start_exit(self,a,c,p,kind,fraction):
        if p.get('exit'):return
        if p['state'] not in ('OPEN','CLOSING'):return
        qty=D(p['qty']) if fraction>=1 else D(p['qty'])*D(fraction)
        price=c.price(p['symbol'])
        try:
            qty=c.quantity(p['symbol'],qty,price,True)
        except ValueError:
            try:
                full_qty=c.quantity(p['symbol'],D(p['qty']),price,True)
                qty=full_qty
                fraction=1.0
            except ValueError:
                self.store.notify(a['uid'],p['id']+':minimum:'+kind,
                    f'⚠️ {p["symbol"]}: بيع {kind} أقل من حدود Binance. لم يُرسل ولم يُعتبر منفذًا؛ راجع حجم المركز.')
                if fraction>=1:p['state']='MANUAL';self.store.save(a)
                return
        p['exit']={'kind':kind,'fraction':fraction,'quantity':dec(qty),
                   'cid':self.cid(a['uid'],p['id'],'exit:'+kind),'phase':'CANCEL_STOP'}
        p['state']='CLOSING';self.store.save(a)
        self._resume_exit(a,c,p)

    def _resume_exit(self,a,c,p):
        x=p['exit']
        if x['phase']=='CANCEL_STOP':
            if not self._cancel_stop(a,c,p):p['exit']=None;self.store.save(a);return
            qty=min(D(x['quantity']),D(p['qty']))
            try:qty=c.quantity(p['symbol'],qty,c.price(p['symbol']),True)
            except ValueError:
                p['exit']=None;p['state']='MANUAL';self.store.save(a);raise
            x['quantity']=dec(qty);x['phase']='SELL';self.store.save(a)
        params={'symbol':p['symbol'],'side':'SELL','type':'MARKET','quantity':x['quantity']}
        try:
            r=self.order(a,c,x['cid'],params)
        except ExchangeError as e:
            if not e.uncertain:
                p['exit']=None
                p['state']='MANUAL' if x['kind']=='SAFETY' else 'OPEN'
                self.store.save(a)
                if p['state']=='OPEN':self._protect(a,c,p)
            raise
        if r['status'] not in TERMINAL:return
        sold=D(r.get('executedQty',0))
        p['qty']=dec(max(D(0),D(p['qty'])-sold))
        if r['status']=='FILLED':
            if x['kind']=='T1_TP':p['stage']=max(1,p['stage']);p['stop']=dec(D(p['entry_price'])*D('1.005'))
            if x['kind']=='T2_TP':p['stage']=2
        p['exit']=None
        
        # فحص ما إذا كانت الكمية المتبقية غبار لا يمكن تداوله على المنصة
        is_dust = False
        try:
            lot = c.rules(p['symbol'])['filters']['LOT_SIZE']
            min_q = D(lot.get('minQty', '0.00001'))
            step_q = D(lot.get('stepSize', '0.00001'))
            if D(p['qty']) < max(min_q, step_q):
                is_dust = True
        except Exception:
            if D(p['qty']) <= D('0.001'):
                is_dust = True

        if D(p['qty']) <= D('0.000000000001') or (is_dust and (x['kind'] in ('T2_TP', 'SAFETY', 'KILL') or p['stage'] >= 2)):
            p['state'] = 'CLOSED'
        else:
            p['state'] = 'OPEN'
        self.store.save(a)
        self.store.notify(a['uid'],p['id']+':exit:'+x['kind'],
            f'📤 Binance {p["symbol"]}: {x["kind"]} — الحالة {r["status"]}، كمية البيع الفعلية {sold}.\nمعرّف الأمر: {r["orderId"]}')
        if p['state']=='OPEN':
            try:c.quantity(p['symbol'],p['qty'],p['stop'],True)
            except ValueError:
                p['state']='MANUAL';self.store.save(a)
                self.store.notify(a['uid'],p['id']+':dust','⚠️ تبقت كمية صغيرة/غير قابلة للحماية حسب حدود Binance. راجعها يدويًا؛ لن يُباع رصيد آخر لتكبيرها.')
                return
            self._protect(a,c,p)

    def _poll_position(self,a,c,p,now):
        if p['state']=='PENDING':
            ledger=self.store.order(a['uid'],p['buy_cid'])
            if ledger and ledger['state']=='REJECTED':
                p['state']='SKIPPED';self.store.save(a);return
            if not ledger:
                p['state']='SKIPPED';self.store.save(a);return
            r=self.query_known(a,c,p['buy_cid'],p['symbol'])
            fill=D(r.get('executedQty',0))
            if r['status'] not in TERMINAL and (fill>0 or now>=p['expires'] or not a['enabled'] or not self.allow_live):
                r=c.cancel(p['symbol'],p['buy_cid']);fill=D(r.get('executedQty',0))
                if r['status'] not in TERMINAL:raise ExchangeError('BUY_CANCEL_UNCONFIRMED',True)
            if r['status'] in TERMINAL:
                if fill>0:
                    net=c.net_filled(p['symbol'],r)
                    p.update(qty=dec(net),original_qty=dec(net),entry_price=dec(D(r['cummulativeQuoteQty'])/fill),
                             filled_at=now,state='OPEN')
                    ref=D(p['plan']['price']);actual=D(p['entry_price'])
                    p['stop']=dec(actual*(D(p['plan']['sl'])/ref))
                    self.store.save(a)
                    self.store.notify(a['uid'],p['id']+':filled',
                        f'✅ شراء منفذ على Binance: {p["symbol"]}\nالكمية الصافية {net} | متوسط الدخول {actual}\nمعرّف الأمر {r["orderId"]}. جارٍ تثبيت الوقف.')
                    self._protect(a,c,p)
                elif (now>=p['expires'] and p['plan']['intent']=='LIMIT' and not p['chased'] and a['enabled'] and self.allow_live and not a.get('halt')):
                    price=c.price(p['symbol']);ref=D(p['plan']['signal_price'])
                    if abs(price/ref-1)>D(a['max_slippage_pct'])/100 or price<=D(p['stop']):
                        p['state']='SKIPPED';self.store.save(a)
                        self.store.notify(a['uid'],p['id']+':no-chase','⏳ أُلغي حد الشراء؛ تجاوز السعر حد المطاردة الآمن.')
                        return
                    qty=c.quantity(p['symbol'],D(p['budget'])*D('.998')/price,price,True)
                    p['buy_cid']=self.cid(a['uid'],p['id'],'chase');p['chased']=True
                    p['buy_params']={'symbol':p['symbol'],'side':'BUY','type':'MARKET','quantity':dec(qty)}
                    self.store.save(a)
                    self.order(a,c,p['buy_cid'],p['buy_params'])
                else:p['state']='SKIPPED';self.store.save(a)
        elif p.get('exit'):
            self._resume_exit(a,c,p)
        elif p['state']=='OPEN':
            # خروج تلقائي فوري بمجرد كسر سعر السوق للوقف لحماية رأس المال الحقيقي
            try:
                curr_p = c.price(p['symbol'])
                if curr_p <= D(p['stop']):
                    self._cancel_stop(a, c, p)
                    self._start_exit(a, c, p, 'SAFETY', 1.0)
                    return
            except Exception:
                pass
            if not p.get('stop_cid'):self._protect(a,c,p);return
            r=self.query_known(a,c,p['stop_cid'],p['symbol'])
            if r['status']=='FILLED':
                p['qty']='0';p['state']='CLOSED';self.store.save(a)
                self.store.notify(a['uid'],p['id']+':stopped',f'🔴 نُفّذ وقف Binance لـ {p["symbol"]}. الأمر {r["orderId"]}.')
            elif r['status']=='PARTIALLY_FILLED':
                return
            elif r['status'] in TERMINAL:
                if self._cancel_stop(a,c,p):self._protect(a,c,p)

    def on_exit(self,uid,event):
        with self.lock:
            a=self.store.account(uid)
            if not a.get('credential'):return
            candidates = [
                p for p in self.active(a)
                if p['symbol'] == event['ticker'] and (
                    p['pool'] == event.get('pool') or 
                    {p.get('pool'), event.get('pool')} <= {'GS-V5-ULTRA', 'V5-ULTRA'}
                ) and p['state'] == 'OPEN'
            ]
            if not candidates: return
            
            # مطابقة المركز المحدد بالمعرف أولاً أو بأقرب سعر شراء
            target_p = None
            if event.get('position_id'):
                for p in candidates:
                    if p['id'] == event['position_id']:
                        target_p = p
                        break
            if not target_p and event.get('buy_price'):
                target_p = min(candidates, key=lambda p: abs(float(p.get('entry_price', 0)) - float(event['buy_price'])))
            if not target_p:
                target_p = candidates[0]
                
            p = target_p
            kind=event['kind']
            pp=self.params.get(p['pool'], self.params.get('GS-V5-ULTRA', {'t1_frac':0.5, 't2_frac_of_rest':1.0}))
            if kind=='T1_TP' and p['stage']>=1:return
            if kind=='T2_TP' and p['stage']>=2:return
            if kind=='T1_TP':
                fraction = pp['t1_frac']
            elif kind=='T2_TP':
                fraction = pp['t2_frac_of_rest'] if p['stage'] >= 1 else 1.0
            else:
                fraction = 1.0
            try:
                if event.get('new_sl'):p['stop']=dec(max(D(p['stop']),D(event['new_sl'])))
                self._start_exit(a,self.client(a),p,kind,fraction)
            except ExchangeError as e:
                if not e.uncertain:
                    self.fault(a,p,e)
            except Exception as e:
                self.fault(a,p,e)
            return

    def update_stops(self,uid,snapshots):
        with self.lock:
            a=self.store.account(uid)
            if not a.get('credential'):return
            for p in self.active(a):
                if p['state']!='OPEN' or p.get('exit'):continue
                for s in snapshots:
                    pool_match = (s['pool']==p['pool'] or {s.get('pool'), p.get('pool')} <= {'GS-V5-ULTRA', 'V5-ULTRA'})
                    if s['ticker']==p['symbol'] and pool_match and float(s['opened_ts'])>=p['source_time'] and D(s['sl'])>D(p['stop']):
                        try:
                            c=self.client(a)
                            if self._cancel_stop(a,c,p):p['stop']=str(s['sl']);self.store.save(a);self._protect(a,c,p)
                        except Exception as e:self.fault(a,p,e)
                        break

    def kill(self,uid):
        with self.lock:
            a=self.store.account(uid);a['enabled']=False;self.store.save(a)
            c=self.client(a)
            for p in self.active(a):
                try:
                    if p['state']=='PENDING':self._poll_position(a,c,p,time.time())
                    if p['state']=='OPEN':self._start_exit(a,c,p,'KILL',1.0)
                except Exception as e:self.fault(a,p,e)
            self.store.notify(uid,'kill:'+str(int(time.time())),
                '🛑 أُوقف فتح صفقات جديدة وطُلب إلغاء/إغلاق أوامر ومراكز هذا البوت فقط. تحقق من Binance؛ قد تبقى أوامر غير مؤكدة أو كميات أقل من الحد الأدنى.')

    def tick(self):
        with self.lock:
            for a in self.store.accounts():
                if not a.get('credential'):continue
                try:c=self.client(a)
                except Exception as e:self.fault(a,{},e);continue
                for row in self.store.unresolved(a['uid']):
                    try:
                        r=c.query(row['symbol'],row['cid'])
                        if r is not None:self.store.order_result(a['uid'],row['cid'],'ACK',r)
                    except Exception:pass
                for p in list(self.active(a)):
                    try:
                        self._poll_position(a,c,p,time.time())
                    except ExchangeError as e:
                        if not e.uncertain:
                            self.fault(a,p,e)
                    except Exception as e:
                        self.fault(a,p,e)
