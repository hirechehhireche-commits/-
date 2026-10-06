#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🔒 TITAN CONTENT PROTECTION - حماية محتوى البوت من النسخ والتسريب
- منع إعادة التوجيه Forward
- منع الحفظ Save
- منع النسخ Copy (قدر الإمكان)
- بصمة خفية لتتبع التسريب
- حماية الكود البرمجي
"""
import hashlib, time, threading
from datetime import datetime, timezone

class ContentProtection:
    """
    حماية محتوى تيليجرام:
    - protect_content=True يمنع Forward/Save في تيليجرام
    - لكن لا يمنع Screenshot 100% على مستوى OS (مستحيل تقنياً حتى لتيليجرام نفسه)
    - نضيف بصمة خفية + واترمارك + حذف تلقائي كرادع
    """
    
    def __init__(self):
        self.enabled = True
        # أحرف غير مرئية للبصمة الخفية (Zero-Width)
        self.zw_chars = ['\u200B', '\u200C', '\u200D', '\uFEFF']  # Zero-width space, non-joiner, joiner, BOM
    
    def encode_user_id(self, user_id: int) -> str:
        """ترميز ID المستخدم في أحرف غير مرئية لتتبع التسريب"""
        try:
            uid_str = str(abs(int(user_id)))[-6:]  # آخر 6 أرقام
            encoded = ""
            for digit in uid_str:
                # كل رقم -> حرف غير مرئي + حرف عادي للتمويه
                encoded += self.zw_chars[int(digit) % len(self.zw_chars)]
            return encoded
        except:
            return ""
    
    def add_watermark(self, text: str, user_id: int, add_visible=False, add_invisible=True) -> str:
        """إضافة بصمة خفية فقط - بدون نص رادع - حماية صامتة"""
        try:
            watermark = ""
            if add_invisible:
                invisible = self.encode_user_id(user_id)
                watermark += invisible
            # لا نص مرئي رادع - حماية صامتة تماماً
            # add_visible=False دائماً حسب طلب المستخدم
            return text + watermark
        except:
            return text
    
    def get_protect_params(self):
        """معاملات الحماية لتيليجرام Bot API"""
        return {
            "protect_content": True,  # يمنع Forward و Save
            "disable_web_page_preview": True,
        }
    
    def should_delete_after(self, message_type="signal"):
        """هل يجب حذف الرسالة بعد مدة؟"""
        # إشارات التداول حساسة - نحذفها بعد 24 ساعة لتقليل التسريب
        if message_type == "signal":
            return 24 * 3600  # 24 ساعة
        elif message_type == "portfolio":
            return 3600  # ساعة
        return None  # لا حذف

# Global instance
PROTECTOR = ContentProtection()

# حماية الكود البرمجي
class CodeProtection:
    """
    حماية الكود البرمجي:
    - الكود موجود على السيرفر (Render) فقط - ليس على جهاز المستخدم
    - المستخدم لا يرى الكود أبداً عبر تيليجرام
    - الحماية: اجعل GitHub repo خاص Private
    - لا ترسل الكود في رسائل تيليجرام
    - استخدم متغيرات بيئة للتوكنات
    - شفّر المفاتيح الحساسة
    """
    
    @staticmethod
    def is_code_exposed():
        """هل الكود مكشوف؟"""
        # الكود على Render - آمن
        # الخطر الوحيد: GitHub repo عام Public
        return False  # الكود على السيرفر فقط
    
    @staticmethod
    def get_security_checklist():
        return [
            "✅ اجعل GitHub repo خاص Private (Settings → Change visibility → Private)",
            "✅ لا تضع BOT_TOKEN في الكود - استخدم Environment Variables في Render",
            "✅ لا ترسل الكود في رسائل تيليجرام",
            "✅ فعّل 2FA على GitHub و Telegram",
            "✅ لا تشارك ملفات .pkl.gz مع أحد - فيها بياناتك",
            "✅ استخدم Render Environment Variables لـ BOT_TOKEN و ADMIN_CHAT_ID",
            "✅ احذف رسائل /bind التي فيها API keys بعد قراءتها",
            "✅ لا تعطي أحد وصول لـ Render Dashboard",
        ]

# للاختبار
if __name__ == "__main__":
    p = ContentProtection()
    text = "🎯 دخول BTCUSDT سعر 50000"
    protected = p.add_watermark(text, 123456789, True, True)
    print("Original:", text)
    print("Protected:", protected)
    print("Protect params:", p.get_protect_params())
    print("\nCode protection checklist:")
    for item in CodeProtection.get_security_checklist():
        print(item)
    print("\n⚠️ ملاحظة: منع Screenshot 100% مستحيل تقنياً على مستوى OS")
    print("حتى تيليجرام نفسه لا يستطيع منعه إلا في Secret Chats على بعض الأجهزة")
    print("لكن protect_content=True يمنع Forward/Save/Copy في تيليجرام + بصمة تتبع")
