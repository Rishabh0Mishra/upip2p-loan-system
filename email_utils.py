import sendgrid
from sendgrid.helpers.mail import Mail
from fastapi import HTTPException

SENDGRID_API_KEY = "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"
FROM_EMAIL = "apitest152@gmail.com"

def send_email(to_email: str, subject: str, html_content: str):
    sg = sendgrid.SendGridAPIClient(api_key=SENDGRID_API_KEY)
    message = Mail(from_email=FROM_EMAIL, to_emails=to_email, subject=subject, html_content=html_content)
    try:
        response = sg.send(message)
        return response.status_code
    except Exception as e:
        print("SendGrid Error:", e)
        raise HTTPException(status_code=500, detail="Failed to send email")
