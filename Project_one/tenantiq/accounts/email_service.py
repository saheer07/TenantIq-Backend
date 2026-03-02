# ==================== utils/email_service.py (CREATE THIS FILE) ====================
from django.core.mail import send_mail
from django.conf import settings
import logging

logger = logging.getLogger(__name__)

def send_otp_email(email, otp_code, purpose="Email Verification"):
    """
    Send OTP email to user
    """
    subject_map = {
        'email_verification': 'Verify Your Email - AI Knowledge Platform',
        'password_reset': 'Reset Your Password - AI Knowledge Platform',
        'login_2fa': 'Two-Factor Authentication Code',
    }
    
    subject = subject_map.get(purpose, 'OTP Verification')
    
    message = f"""
Hello,

Your verification code is: {otp_code}

This code is valid for 10 minutes.

⚠️ IMPORTANT: Do not share this code with anyone.

If you didn't request this code, please ignore this email or contact support.

Best regards,
AI Knowledge Platform Team
"""

    html_message = f"""
<!DOCTYPE html>
<html>
<head>
    <style>
        body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
        .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
        .header {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 30px; text-align: center; border-radius: 10px 10px 0 0; }}
        .content {{ background: #f8f9fa; padding: 30px; border-radius: 0 0 10px 10px; }}
        .otp-box {{ background: white; border: 2px dashed #667eea; padding: 20px; text-align: center; margin: 20px 0; border-radius: 8px; }}
        .otp-code {{ font-size: 32px; font-weight: bold; color: #667eea; letter-spacing: 5px; }}
        .warning {{ background: #fff3cd; border-left: 4px solid #ffc107; padding: 15px; margin: 20px 0; }}
        .footer {{ text-align: center; margin-top: 30px; color: #6c757d; font-size: 12px; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🔐 Verification Code</h1>
        </div>
        <div class="content">
            <h2>Hello!</h2>
            <p>You requested a verification code for your account. Please use the code below:</p>
            
            <div class="otp-box">
                <div class="otp-code">{otp_code}</div>
                <p style="color: #6c757d; margin-top: 10px;">Valid for 10 minutes</p>
            </div>
            
            <div class="warning">
                <strong>⚠️ Security Warning:</strong> Never share this code with anyone. 
                Our team will never ask for this code.
            </div>
            
            <p>If you didn't request this code, please ignore this email or contact our support team.</p>
            
            <div class="footer">
                <p>Best regards,<br>AI Knowledge Platform Team</p>
                <p>© 2025 AI Knowledge Platform. All rights reserved.</p>
            </div>
        </div>
    </div>
</body>
</html>
"""

    try:
        send_mail(
            subject=subject,
            message=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[email],
            html_message=html_message,
            fail_silently=False,
        )
        logger.info(f"OTP email sent successfully to {email}")
        return True
    except Exception as e:
        logger.error(f"Failed to send OTP email to {email}: {str(e)}")
        # For development, print OTP to console
        print(f"\n{'='*50}")
        print(f"📧 OTP EMAIL (DEV MODE)")
        print(f"{'='*50}")
        print(f"To: {email}")
        print(f"Purpose: {purpose}")
        print(f"OTP Code: {otp_code}")
        print(f"{'='*50}\n")
        return False