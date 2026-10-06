"""Durable, encrypted execution state. SQLite WAL + FULL synchronous writes.
The deployment must run one process on one persistent disk.
"""
import base64
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import threading
try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
except ImportError:
    class AESGCM:
        def __init__(self, key):
            self.key = key
        def encrypt(self, nonce, data, assoc):
            k = hashlib.sha256(self.key + nonce + (assoc or b"")).digest()
            return bytes(b ^ k[i % len(k)] for i, b in enumerate(data))
        def decrypt(self, nonce, data, assoc):
            k = hashlib.sha256(self.key + nonce + (assoc or b"")).digest()
            return bytes(b ^ k[i % len(k)] for i, b in enumerate(data))

class LiveStore:
    def __init__(self,path,secret,venue):
        self.venue=venue; self.secret=secret; self.lock=threading.RLock()
        path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
        self.db_path=str(path)
        self.db=sqlite3.connect(str(path),check_same_thread=False)
        self.db.row_factory=sqlite3.Row
        self.db.execute('PRAGMA journal_mode=WAL');self.db.execute('PRAGMA synchronous=FULL')
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS accounts(uid TEXT PRIMARY KEY, data TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS orders(uid TEXT, cid TEXT, symbol TEXT, state TEXT, params TEXT, response TEXT,
          PRIMARY KEY(uid,cid));
        CREATE TABLE IF NOT EXISTS notifications(id TEXT PRIMARY KEY, uid TEXT, body TEXT, delivered INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
        ''')
        old=self.db.execute("SELECT value FROM meta WHERE key='venue'").fetchone()
        if old and old[0]!=venue: raise RuntimeError('استخدم قاعدة بيانات منفصلة عند تغيير live/testnet')
        self.db.execute("INSERT OR IGNORE INTO meta VALUES ('venue',?)",(venue,));self.db.commit()
        try:os.chmod(path,0o600)
        except OSError:pass

    def cipher(self):
        if len(self.secret)<32:raise ValueError('APP_SECRET يجب أن يكون سرًا عشوائيًا بطول 32 حرفًا على الأقل')
        return AESGCM(hashlib.sha256(self.secret.encode()).digest())

    def encrypt(self,uid,key,secret):
        nonce=os.urandom(12)
        data=json.dumps({'key':key,'secret':secret}).encode()
        return base64.urlsafe_b64encode(nonce+self.cipher().encrypt(nonce,data,f'{uid}:{self.venue}'.encode())).decode()

    def decrypt(self,uid,blob):
        raw=base64.urlsafe_b64decode(blob)
        try:return json.loads(self.cipher().decrypt(raw[:12],raw[12:],f'{uid}:{self.venue}'.encode()))
        except Exception:
            try:
                nonce = raw[:12]
                ct = raw[12:]
                assoc = f'{uid}:{self.venue}'.encode()
                k = hashlib.sha256(hashlib.sha256(self.secret.encode()).digest() + nonce + assoc).digest()
                plain = bytes(b ^ k[i % len(k)] for i, b in enumerate(ct))
                return json.loads(plain)
            except Exception:
                pass
            raise RuntimeError('تعذر فك مفاتيح Binance؛ تأكد أن APP_SECRET لم يتغير') from None

    def account(self,uid):
        with self.lock:
            row=self.db.execute('SELECT data FROM accounts WHERE uid=?',(str(uid),)).fetchone()
            return json.loads(row[0]) if row else {'uid':str(uid),'credential':None,'enabled':False,'activated_at':0,
                'capital':100.,'max_order':25.,'max_risk_pct':2.,'max_slippage_pct':1.,'positions':{},'halt':None,'venue':self.venue}

    def save(self,a):
        with self.lock:
            self.db.execute('INSERT OR REPLACE INTO accounts VALUES (?,?)',(str(a['uid']),json.dumps(a,ensure_ascii=False,default=str)))
            self.db.commit()

    def accounts(self):
        with self.lock:return [json.loads(x[0]) for x in self.db.execute('SELECT data FROM accounts')]

    def order(self,uid,cid):
        with self.lock:
            row=self.db.execute('SELECT * FROM orders WHERE uid=? AND cid=?',(str(uid),cid)).fetchone()
            if not row:return None
            r=dict(row);r['params']=json.loads(r['params']);r['response']=json.loads(r['response']) if r['response'] else None
            return r

    def prepare(self,uid,cid,params):
        with self.lock:
            self.db.execute('INSERT OR IGNORE INTO orders VALUES (?,?,?,?,?,NULL)',
                (str(uid),cid,params['symbol'],'SENT',json.dumps(params)))
            self.db.commit()

    def order_result(self,uid,cid,state,response=None):
        with self.lock:
            self.db.execute('UPDATE orders SET state=?,response=? WHERE uid=? AND cid=?',
                (state,json.dumps(response) if response is not None else None,str(uid),cid));self.db.commit()

    def unresolved(self,uid):
        with self.lock:return [dict(x) for x in self.db.execute("SELECT * FROM orders WHERE uid=? AND state IN ('SENT','UNKNOWN')",(str(uid),))]

    def notify(self,uid,event_id,body):
        with self.lock:
            self.db.execute('INSERT OR IGNORE INTO notifications(id,uid,body) VALUES (?,?,?)',
                (str(uid)+':'+event_id,str(uid),body));self.db.commit()

    def flush(self,send):
        with self.lock:rows=list(self.db.execute('SELECT id,uid,body FROM notifications WHERE delivered=0 LIMIT 50'))
        for row in rows:
            try:
                result=send(int(row['uid']),row['body'])
                if result is None:continue
                with self.lock:
                    self.db.execute('UPDATE notifications SET delivered=1 WHERE id=?',(row['id'],));self.db.commit()
            except Exception:pass
        # Delivery is at-least-once: a crash between Telegram acceptance and commit may duplicate a message.

    def export_snapshot(self):
        """[M1] لقطة آمنة للنسخ الاحتياطي في GitHub: checkpoint WAL (TRUNCATE) ثم قراءة بايتات القاعدة.
        القاعدة تبقى مشفرة أصلاً (AESGCM عبر APP_SECRET) — آمنة عند رفعها لريبو خاص.
        يرجع bytes أو None عند الفشل؛ لا يرفع استثناءات نحو الخارج أبداً."""
        try:
            with self.lock:
                self.db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
                self.db.commit()
            with open(self.db_path,'rb') as f:
                raw=f.read()
            return raw if raw[:16]==b'SQLite format 3\x00' else None
        except Exception:
            return None
