import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from typing import Optional, List
import models
import schemas
from config import settings
import logging
import json
from websocket_manager import manager  # <-- your WS connection manager here
import asyncio  # For async calls

logger = logging.getLogger(__name__)

class NotificationService:
    def __init__(self, db: Session):
        self.db = db
    
    def create_notification(
        self,
        user_id: int,
        notification_type: models.NotificationType,
        title: str,
        message: str,
        channel: models.NotificationChannel = models.NotificationChannel.IN_APP,
        loan_id: Optional[int] = None,
        payment_id: Optional[int] = None,
        scheduled_for: Optional[datetime] = None
    ) -> models.Notification:
        """Create a new notification"""
        notification = models.Notification(
            user_id=user_id,
            type=notification_type,
            channel=channel,
            title=title,
            message=message,
            loan_id=loan_id,
            payment_id=payment_id,
            scheduled_for=scheduled_for or datetime.now()
        )
        
        self.db.add(notification)
        self.db.commit()
        self.db.refresh(notification)
        
        # Send immediately if not scheduled
        if not scheduled_for or scheduled_for <= datetime.now():
            # Send the notification normally
            self._send_notification(notification)
            # And trigger real-time push if channel is IN_APP
            if notification.channel == models.NotificationChannel.IN_APP:
                # Schedule async WS send (fire and forget)
                asyncio.create_task(self._send_realtime_ws_notification(notification))
        
        return notification
    
    def _send_notification(self, notification: models.Notification):
        """Send notification via the specified channel"""
        try:
            if notification.channel == models.NotificationChannel.EMAIL:
                self._send_email(notification)
            elif notification.channel == models.NotificationChannel.SMS:
                self._send_sms(notification)
            elif notification.channel == models.NotificationChannel.PUSH:
                self._send_push(notification)
            # IN_APP notifications don't need to be "sent" through external channels
            
            notification.is_sent = True
            notification.sent_at = datetime.now()
            self.db.commit()
            
        except Exception as e:
            logger.error(f"Failed to send notification {notification.id}: {str(e)}")
    
    async def _send_realtime_ws_notification(self, notification: models.Notification):
        """Send real-time notification through WebSocket"""
        try:
            payload = {
                "id": notification.id,
                "type": notification.type.name,
                "title": notification.title,
                "message": notification.message,
                "loan_id": notification.loan_id,
                "payment_id": notification.payment_id,
                "created_at": notification.created_at.isoformat()
            }
            await manager.send_personal_message(json.dumps(payload), notification.user_id)
        except Exception as e:
            logger.error(f"Failed to send real-time WS notification {notification.id}: {str(e)}")
    
    def _send_email(self, notification: models.Notification):
        """Send email notification"""
        user = self.db.query(models.User).filter(models.User.id == notification.user_id).first()
        if not user or not user.email:
            return
        
        msg = MIMEMultipart()
        msg['From'] = settings.smtp_user
        msg['To'] = user.email
        msg['Subject'] = notification.title
        
        body = notification.message
        msg.attach(MIMEText(body, 'plain'))
        
        try:
            server = smtplib.SMTP(settings.smtp_host, settings.smtp_port)
            server.starttls()
            server.login(settings.smtp_user, settings.smtp_password)
            text = msg.as_string()
            server.sendmail(settings.smtp_user, user.email, text)
            server.quit()
        except Exception as e:
            logger.error(f"Email sending failed: {str(e)}")
            raise
    
    def _send_sms(self, notification: models.Notification):
        """Send SMS notification (placeholder - integrate with your SMS provider)"""
        user = self.db.query(models.User).filter(models.User.id == notification.user_id).first()
        if not user or not user.phone:
            return
        
        # Integrate with SMS provider like Twilio, AWS SNS, etc.
        logger.info(f"SMS would be sent to {user.phone}: {notification.message}")
    
    def _send_push(self, notification: models.Notification):
        """Send push notification (placeholder - integrate with FCM, etc.)"""
        # Integrate with Firebase Cloud Messaging or similar
        logger.info(f"Push notification would be sent: {notification.message}")
    
    def get_user_notifications(
        self,
        user_id: int,
        unread_only: bool = False,
        limit: int = 50
    ) -> List[models.Notification]:
        """Get notifications for a user"""
        query = self.db.query(models.Notification).filter(
            models.Notification.user_id == user_id
        )
        
        if unread_only:
            query = query.filter(models.Notification.is_read == False)
        
        return query.order_by(models.Notification.created_at.desc()).limit(limit).all()
    
    def mark_as_read(self, notification_id: int, user_id: int) -> bool:
        """Mark notification as read"""
        notification = self.db.query(models.Notification).filter(
            models.Notification.id == notification_id,
            models.Notification.user_id == user_id
        ).first()
        
        if notification:
            notification.is_read = True
            self.db.commit()
            return True
        return False
    
    def send_loan_request_notification(self, loan: models.Loan):
        """Send notification when a loan is requested"""
        self.create_notification(
            user_id=loan.lender_id,
            notification_type=models.NotificationType.LOAN_REQUEST,
            title="New Loan Request",
            message=f"You have received a loan request for ₹{loan.principal_amount} from {loan.borrower.name}",
            channel=models.NotificationChannel.EMAIL,
            loan_id=loan.id
        )
    
    def send_loan_approved_notification(self, loan: models.Loan):
        """Send notification when loan is approved"""
        self.create_notification(
            user_id=loan.borrower_id,
            notification_type=models.NotificationType.LOAN_APPROVED,
            title="Loan Approved!",
            message=f"Your loan request for ₹{loan.principal_amount} has been approved by {loan.lender.name}",
            channel=models.NotificationChannel.EMAIL,
            loan_id=loan.id
        )
    
    def send_loan_rejected_notification(self, loan: models.Loan):
        """Send notification when loan is rejected"""
        self.create_notification(
            user_id=loan.borrower_id,
            notification_type=models.NotificationType.LOAN_REJECTED,
            title="Loan Request Declined",
            message=f"Your loan request for ₹{loan.principal_amount} has been declined",
            channel=models.NotificationChannel.EMAIL,
            loan_id=loan.id
        )
    
    def send_payment_due_notification(self, payment: models.Payment):
        """Send notification for upcoming payment"""
        loan = payment.loan
        self.create_notification(
            user_id=loan.borrower_id,
            notification_type=models.NotificationType.PAYMENT_DUE,
            title="Payment Due Reminder",
            message=f"Your payment of ₹{payment.amount} for loan #{loan.id} is due on {payment.due_date.strftime('%Y-%m-%d')}",
            channel=models.NotificationChannel.EMAIL,
            loan_id=loan.id,
            payment_id=payment.id
        )
    
    def send_payment_overdue_notification(self, payment: models.Payment):
        """Send notification for overdue payment"""
        loan = payment.loan
        days_overdue = (datetime.now() - payment.due_date).days
        
        self.create_notification(
            user_id=loan.borrower_id,
            notification_type=models.NotificationType.PAYMENT_OVERDUE,
            title="Payment Overdue",
            message=f"Your payment of ₹{payment.amount} for loan #{loan.id} is {days_overdue} days overdue",
            channel=models.NotificationChannel.EMAIL,
            loan_id=loan.id,
            payment_id=payment.id
        )
    
    def send_payment_received_notification(self, payment: models.Payment):
        """Send notification when payment is received"""
        loan = payment.loan
        
        # Notify lender
        self.create_notification(
            user_id=loan.lender_id,
            notification_type=models.NotificationType.PAYMENT_RECEIVED,
            title="Payment Received",
            message=f"Received payment of ₹{payment.amount} for loan #{loan.id} from {loan.borrower.name}",
            channel=models.NotificationChannel.EMAIL,
            loan_id=loan.id,
            payment_id=payment.id
        )
    
    def schedule_payment_reminders(self):
        """Schedule payment reminder notifications"""
        due_date = datetime.now() + timedelta(days=3)
        upcoming_payments = self.db.query(models.Payment).filter(
            models.Payment.status == models.PaymentStatus.pending,
            models.Payment.due_date.between(datetime.now(), due_date)
        ).all()
        
        for payment in upcoming_payments:
            existing_notification = self.db.query(models.Notification).filter(
                models.Notification.payment_id == payment.id,
                models.Notification.type == models.NotificationType.PAYMENT_DUE
            ).first()
            
            if not existing_notification:
                self.send_payment_due_notification(payment)
    
    def check_overdue_payments(self):
        """Check and notify about overdue payments"""
        overdue_payments = self.db.query(models.Payment).filter(
            models.Payment.status == models.PaymentStatus.pending,
            models.Payment.due_date < datetime.now()
        ).all()
        
        for payment in overdue_payments:
            loan = payment.loan
            if loan.sub_status != models.LoanSubStatus.overdue:
                loan.sub_status = models.LoanSubStatus.overdue
                self.db.commit()
            
            last_notification = self.db.query(models.Notification).filter(
                models.Notification.payment_id == payment.id,
                models.Notification.type == models.NotificationType.PAYMENT_OVERDUE,
                models.Notification.created_at > datetime.now() - timedelta(days=1)
            ).first()
            
            if not last_notification:
                self.send_payment_overdue_notification(payment)

# Helper functions for easy access
def get_notification_service(db: Session) -> NotificationService:
    return NotificationService(db)

def send_loan_notifications(db: Session, loan: models.Loan, action: str):
    service = NotificationService(db)
    
    if action == "created":
        service.send_loan_request_notification(loan)
    elif action == "approved":
        service.send_loan_approved_notification(loan)
    elif action == "rejected":
        service.send_loan_rejected_notification(loan)
