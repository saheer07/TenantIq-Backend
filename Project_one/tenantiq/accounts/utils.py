from django.core.mail import EmailMultiAlternatives
from django.conf import settings

def send_otp_email(email: str, otp: str, purpose: str = "verify your email") -> None:
    subject = "Your TenantIQ Verification Code"
    
    text_content = f"""
Your OTP is: {otp}

This OTP is valid for 10 minutes.
Do not share this OTP with anyone.
"""

    html_content = f"""
<div style="font-family: Arial, sans-serif; max-width: 480px; margin: auto; padding: 24px; border: 1px solid #e0e0e0; border-radius: 8px;">
    <h2 style="color: #1a1a1a;">TenantIQ Verification</h2>
    <p style="color: #444;">Use the OTP below to {purpose}:</p>
    
    <div style="font-size: 32px; font-weight: bold; letter-spacing: 8px; color: #4F46E5; 
                background: #f5f5ff; padding: 16px; border-radius: 6px; text-align: center;">
        {otp}
    </div>
    
    <p style="color: #666; margin-top: 16px;">
        This code expires in <strong>10 minutes</strong>.<br>
        Never share this code with anyone.
    </p>
    <hr style="border: none; border-top: 1px solid #eee;">
    <p style="color: #999; font-size: 12px;">
        If you didn't request this, you can safely ignore this email.
    </p>
</div>
"""

    msg = EmailMultiAlternatives(
        subject=subject,
        body=text_content,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[email],
    )
    msg.attach_alternative(html_content, "text/html")
    msg.send(fail_silently=False)