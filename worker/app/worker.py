"""
PCC Platform - Celery Worker Configuration

This module initializes the Celery application and registers background tasks
for the PCC Platform worker service. It handles AI processing, scheduled jobs,
and other asynchronous operations.
"""
import os
import time
from typing import Any, Dict, List, Optional, Tuple

import structlog
from celery import Celery, Task, signals
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import AnyUrl, BaseSettings, Field
from pydantic_settings import SettingsConfigDict

# Configure structured logging
logger = structlog.get_logger(__name__)

# =====================================================
# Settings Configuration
# =====================================================
class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    # Core settings
    app_env: str = Field("production", env="APP_ENV")
    debug: bool = Field(False, env="DEBUG")
    
    # MongoDB settings
    mongodb_uri: AnyUrl = Field(..., env="MONGODB_URI")
    mongodb_db_name: str = Field("pcc", env="MONGODB_DB_NAME")
    mongodb_max_pool_size: int = Field(10, env="MONGODB_MAX_POOL_SIZE")
    
    # Celery settings
    celery_broker_url: str = Field("memory://", env="CELERY_BROKER_URL")
    celery_result_backend: str = Field("memory://", env="CELERY_RESULT_BACKEND")
    celery_task_serializer: str = Field("json", env="CELERY_TASK_SERIALIZER")
    celery_result_serializer: str = Field("json", env="CELERY_RESULT_SERIALIZER")
    celery_accept_content: List[str] = Field(["json"], env="CELERY_ACCEPT_CONTENT")
    celery_task_acks_late: bool = Field(True, env="CELERY_TASK_ACKS_LATE")
    celery_worker_prefetch_multiplier: int = Field(1, env="CELERY_WORKER_PREFETCH_MULTIPLIER")
    celery_worker_concurrency: int = Field(2, env="CONCURRENCY")
    celery_worker_max_tasks_per_child: int = Field(100, env="MAX_TASKS_PER_CHILD")
    celery_task_time_limit: int = Field(3600, env="CELERY_TASK_TIME_LIMIT")  # 1 hour
    celery_task_soft_time_limit: int = Field(3300, env="CELERY_TASK_SOFT_TIME_LIMIT")  # 55 minutes
    
    # OpenAI settings
    openai_api_key: Optional[str] = Field(None, env="OPENAI_API_KEY")
    openai_model: str = Field("gpt-4", env="OPENAI_MODEL")
    
    # Storage settings
    storage_type: str = Field("local", env="STORAGE_TYPE")  # local, s3, gcs
    storage_bucket: Optional[str] = Field(None, env="STORAGE_BUCKET")
    
    # Model configuration
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )
    
    @property
    def is_development(self) -> bool:
        """Check if the application is running in development mode."""
        return self.app_env.lower() == "development"
    
    @property
    def is_production(self) -> bool:
        """Check if the application is running in production mode."""
        return self.app_env.lower() == "production"


# Create global settings instance
settings = Settings()

# =====================================================
# Database Connection
# =====================================================
class Database:
    """Database connection manager for Celery tasks."""
    
    client: Optional[AsyncIOMotorClient] = None
    db = None
    
    @classmethod
    def connect(cls):
        """Connect to MongoDB."""
        logger.info("Connecting to MongoDB", uri=settings.mongodb_uri)
        cls.client = AsyncIOMotorClient(
            str(settings.mongodb_uri),
            maxPoolSize=settings.mongodb_max_pool_size,
        )
        cls.db = cls.client[settings.mongodb_db_name]
        logger.info("Connected to MongoDB", database=settings.mongodb_db_name)
    
    @classmethod
    def disconnect(cls):
        """Disconnect from MongoDB."""
        if cls.client:
            logger.info("Disconnecting from MongoDB")
            cls.client.close()
            cls.client = None
            cls.db = None


# =====================================================
# Celery Application Configuration
# =====================================================
celery_app = Celery(
    "pcc_worker",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)

# Configure Celery
celery_app.conf.update(
    task_serializer=settings.celery_task_serializer,
    result_serializer=settings.celery_result_serializer,
    accept_content=settings.celery_accept_content,
    task_acks_late=settings.celery_task_acks_late,
    worker_prefetch_multiplier=settings.celery_worker_prefetch_multiplier,
    worker_concurrency=settings.celery_worker_concurrency,
    worker_max_tasks_per_child=settings.celery_worker_max_tasks_per_child,
    task_time_limit=settings.celery_task_time_limit,
    task_soft_time_limit=settings.celery_task_soft_time_limit,
    task_routes={
        "app.tasks.transcribe_audio": {"queue": "transcription"},
        "app.tasks.analyze_transcript": {"queue": "analysis"},
        "app.tasks.generate_pdf": {"queue": "documents"},
        "app.tasks.send_email": {"queue": "emails"},
    },
    task_default_queue="default",
    task_queues={
        "transcription": {"exchange": "pcc", "routing_key": "transcription"},
        "analysis": {"exchange": "pcc", "routing_key": "analysis"},
        "documents": {"exchange": "pcc", "routing_key": "documents"},
        "emails": {"exchange": "pcc", "routing_key": "emails"},
        "default": {"exchange": "pcc", "routing_key": "default"},
    },
)

# Include task modules
celery_app.autodiscover_tasks(["app.tasks"])

# =====================================================
# Celery Signals
# =====================================================
@signals.worker_init.connect
def init_worker(**kwargs):
    """Initialize worker connections and services."""
    logger.info("Initializing worker", pid=os.getpid())
    
    # Connect to database
    Database.connect()
    
    # Initialize OpenAI if API key is provided
    if settings.openai_api_key:
        import openai
        openai.api_key = settings.openai_api_key
        logger.info("OpenAI API initialized", model=settings.openai_model)


@signals.worker_shutdown.connect
def shutdown_worker(**kwargs):
    """Clean up worker connections."""
    logger.info("Shutting down worker", pid=os.getpid())
    
    # Disconnect from database
    Database.disconnect()


@signals.task_prerun.connect
def task_prerun(task_id, task, *args, **kwargs):
    """Log task start."""
    logger.info(
        "Task started",
        task_id=task_id,
        task_name=task.name,
        args=args,
        kwargs=kwargs,
    )


@signals.task_postrun.connect
def task_postrun(task_id, task, retval, state, *args, **kwargs):
    """Log task completion."""
    logger.info(
        "Task completed",
        task_id=task_id,
        task_name=task.name,
        state=state,
        runtime=time.time() - task.request.start_time,
    )


@signals.task_failure.connect
def task_failure(task_id, exception, traceback, einfo, *args, **kwargs):
    """Log task failure."""
    logger.error(
        "Task failed",
        task_id=task_id,
        exception=str(exception),
        traceback=str(einfo),
    )


# =====================================================
# Base Task Class
# =====================================================
class BaseTask(Task):
    """Base task class with error handling and retry logic."""
    
    # Default retry settings
    autoretry_for = (Exception,)
    retry_kwargs = {"max_retries": 3, "countdown": 5}
    retry_backoff = True
    retry_backoff_max = 600  # 10 minutes
    retry_jitter = True
    
    def on_failure(self, exc, task_id, args, kwargs, einfo):
        """Handle task failure."""
        logger.error(
            "Task execution failed",
            task_id=task_id,
            task_name=self.name,
            exception=str(exc),
            traceback=str(einfo),
            args=args,
            kwargs=kwargs,
        )
        
        # Update task status in database
        try:
            collection = Database.db.tasks
            collection.update_one(
                {"task_id": task_id},
                {"$set": {
                    "status": "failed",
                    "error": str(exc),
                    "completed_at": time.time(),
                }},
            )
        except Exception as e:
            logger.error("Failed to update task status", error=str(e))
        
        super().on_failure(exc, task_id, args, kwargs, einfo)
    
    def on_success(self, retval, task_id, args, kwargs):
        """Handle task success."""
        logger.info(
            "Task execution succeeded",
            task_id=task_id,
            task_name=self.name,
            args=args,
            kwargs=kwargs,
        )
        
        # Update task status in database
        try:
            collection = Database.db.tasks
            collection.update_one(
                {"task_id": task_id},
                {"$set": {
                    "status": "completed",
                    "result": retval,
                    "completed_at": time.time(),
                }},
            )
        except Exception as e:
            logger.error("Failed to update task status", error=str(e))
        
        super().on_success(retval, task_id, args, kwargs)


# =====================================================
# Task Definitions
# =====================================================
@celery_app.task(base=BaseTask, bind=True, name="app.tasks.transcribe_audio")
def transcribe_audio(self, session_id: str, audio_url: str, language: str = "en") -> Dict[str, Any]:
    """
    Transcribe audio from a coaching session.
    
    Args:
        session_id: ID of the session to transcribe
        audio_url: URL to the audio file
        language: Language code for transcription
        
    Returns:
        Dict containing transcription results
    """
    logger.info("Starting audio transcription", session_id=session_id, audio_url=audio_url)
    
    # Record task start in database
    task_id = self.request.id
    collection = Database.db.tasks
    collection.insert_one({
        "task_id": task_id,
        "type": "transcription",
        "session_id": session_id,
        "status": "processing",
        "created_at": time.time(),
    })
    
    try:
        # Download audio file
        # This would use appropriate storage client based on settings.storage_type
        audio_path = download_audio(audio_url)
        
        # Transcribe audio using OpenAI Whisper
        if settings.openai_api_key:
            import openai
            
            logger.info("Sending audio to OpenAI for transcription", file_path=audio_path)
            
            with open(audio_path, "rb") as audio_file:
                transcript = openai.Audio.transcribe(
                    file=audio_file,
                    model="whisper-1",
                    language=language,
                    response_format="verbose_json",
                )
            
            # Process transcript
            words = transcript.get("words", [])
            text = transcript.get("text", "")
            
            # Store transcript in database
            transcript_id = store_transcript(session_id, text, words, language)
            
            # Clean up temporary file
            os.remove(audio_path)
            
            # Return results
            return {
                "session_id": session_id,
                "transcript_id": transcript_id,
                "language": language,
                "duration": transcript.get("duration", 0),
                "word_count": len(words),
            }
        else:
            raise ValueError("OpenAI API key not configured")
    
    except Exception as e:
        logger.exception("Transcription failed", session_id=session_id, error=str(e))
        raise


@celery_app.task(base=BaseTask, bind=True, name="app.tasks.analyze_transcript")
def analyze_transcript(self, session_id: str, transcript_id: str) -> Dict[str, Any]:
    """
    Analyze a session transcript with AI.
    
    Args:
        session_id: ID of the session
        transcript_id: ID of the transcript to analyze
        
    Returns:
        Dict containing analysis results
    """
    logger.info("Starting transcript analysis", session_id=session_id, transcript_id=transcript_id)
    
    # Record task start in database
    task_id = self.request.id
    collection = Database.db.tasks
    collection.insert_one({
        "task_id": task_id,
        "type": "analysis",
        "session_id": session_id,
        "transcript_id": transcript_id,
        "status": "processing",
        "created_at": time.time(),
    })
    
    try:
        # Retrieve transcript from database
        transcript = get_transcript(transcript_id)
        if not transcript:
            raise ValueError(f"Transcript not found: {transcript_id}")
        
        # Get session metadata
        session = get_session(session_id)
        if not session:
            raise ValueError(f"Session not found: {session_id}")
        
        # Analyze transcript using OpenAI
        if settings.openai_api_key:
            import openai
            
            logger.info("Sending transcript to OpenAI for analysis")
            
            # Prepare prompt with session context
            prompt = generate_analysis_prompt(transcript, session)
            
            # Call OpenAI API
            response = openai.ChatCompletion.create(
                model=settings.openai_model,
                messages=[
                    {"role": "system", "content": prompt["system"]},
                    {"role": "user", "content": prompt["user"]},
                ],
                temperature=0.2,
                max_tokens=2000,
            )
            
            # Parse response
            analysis_text = response.choices[0].message.content
            analysis = parse_analysis_response(analysis_text)
            
            # Store analysis in database
            analysis_id = store_analysis(session_id, transcript_id, analysis)
            
            # Return results
            return {
                "session_id": session_id,
                "transcript_id": transcript_id,
                "analysis_id": analysis_id,
                "summary": analysis.get("summary", ""),
                "action_items_count": len(analysis.get("action_items", [])),
                "topics": analysis.get("topics", []),
                "sentiment": analysis.get("sentiment", "neutral"),
            }
        else:
            raise ValueError("OpenAI API key not configured")
    
    except Exception as e:
        logger.exception("Analysis failed", session_id=session_id, error=str(e))
        raise


@celery_app.task(base=BaseTask, bind=True, name="app.tasks.generate_pdf")
def generate_pdf(self, session_id: str, template: str = "session_summary") -> Dict[str, Any]:
    """
    Generate a PDF report for a coaching session.
    
    Args:
        session_id: ID of the session
        template: Template name for the PDF
        
    Returns:
        Dict containing PDF generation results
    """
    logger.info("Starting PDF generation", session_id=session_id, template=template)
    
    # Implementation would go here
    # This would retrieve session data, transcript, analysis
    # Then use a library like ReportLab or WeasyPrint to generate a PDF
    
    return {
        "session_id": session_id,
        "pdf_url": f"https://storage.example.com/reports/{session_id}.pdf",
        "template": template,
    }


@celery_app.task(base=BaseTask, bind=True, name="app.tasks.send_email")
def send_email(self, recipient: str, template: str, context: Dict[str, Any]) -> Dict[str, Any]:
    """
    Send an email using a template.
    
    Args:
        recipient: Email recipient
        template: Template name
        context: Template context variables
        
    Returns:
        Dict containing email sending results
    """
    logger.info("Sending email", recipient=recipient, template=template)
    
    # Implementation would go here
    # This would use a service like SendGrid or SMTP to send emails
    
    return {
        "recipient": recipient,
        "template": template,
        "sent_at": time.time(),
        "status": "sent",
    }


# =====================================================
# Helper Functions
# =====================================================
def download_audio(url: str) -> str:
    """
    Download audio file from URL to temporary location.
    
    Args:
        url: URL of the audio file
        
    Returns:
        Path to the downloaded file
    """
    import tempfile
    import httpx
    
    logger.info("Downloading audio file", url=url)
    
    # Create temporary file
    temp_dir = tempfile.gettempdir()
    temp_path = os.path.join(temp_dir, f"audio_{int(time.time())}.mp3")
    
    # Download file
    with httpx.stream("GET", url) as response:
        response.raise_for_status()
        with open(temp_path, "wb") as f:
            for chunk in response.iter_bytes():
                f.write(chunk)
    
    logger.info("Audio file downloaded", path=temp_path, size_bytes=os.path.getsize(temp_path))
    return temp_path


def store_transcript(session_id: str, text: str, words: List[Dict], language: str) -> str:
    """
    Store transcript in database.
    
    Args:
        session_id: ID of the session
        text: Full transcript text
        words: List of word objects with timestamps
        language: Language code
        
    Returns:
        ID of the created transcript
    """
    from bson.objectid import ObjectId
    
    # Create transcript document
    transcript = {
        "_id": ObjectId(),
        "session_id": session_id,
        "text": text,
        "words": words,
        "language": language,
        "created_at": time.time(),
    }
    
    # Insert into database
    collection = Database.db.transcripts
    collection.insert_one(transcript)
    
    logger.info("Transcript stored", transcript_id=str(transcript["_id"]), session_id=session_id)
    return str(transcript["_id"])


def get_transcript(transcript_id: str) -> Dict:
    """
    Retrieve transcript from database.
    
    Args:
        transcript_id: ID of the transcript
        
    Returns:
        Transcript document
    """
    from bson.objectid import ObjectId
    
    collection = Database.db.transcripts
    transcript = collection.find_one({"_id": ObjectId(transcript_id)})
    
    if transcript:
        # Convert ObjectId to string for serialization
        transcript["_id"] = str(transcript["_id"])
    
    return transcript


def get_session(session_id: str) -> Dict:
    """
    Retrieve session from database.
    
    Args:
        session_id: ID of the session
        
    Returns:
        Session document
    """
    from bson.objectid import ObjectId
    
    collection = Database.db.sessions
    session = collection.find_one({"_id": ObjectId(session_id)})
    
    if session:
        # Convert ObjectId to string for serialization
        session["_id"] = str(session["_id"])
        
        # Fetch related coach and client info
        if "coach_id" in session:
            coach = Database.db.coaches.find_one({"_id": ObjectId(session["coach_id"])})
            if coach:
                session["coach"] = {
                    "id": str(coach["_id"]),
                    "name": coach.get("name", ""),
                    "email": coach.get("email", ""),
                }
        
        if "client_id" in session:
            client = Database.db.clients.find_one({"_id": ObjectId(session["client_id"])})
            if client:
                session["client"] = {
                    "id": str(client["_id"]),
                    "name": client.get("name", ""),
                    "email": client.get("email", ""),
                }
    
    return session


def generate_analysis_prompt(transcript: Dict, session: Dict) -> Dict[str, str]:
    """
    Generate prompt for OpenAI analysis.
    
    Args:
        transcript: Transcript document
        session: Session document
        
    Returns:
        Dict with system and user prompts
    """
    # System prompt instructs the model on its role and output format
    system_prompt = """
    You are an expert coach analyst. Your task is to analyze a coaching session transcript
    and extract key insights. Provide your analysis in the following JSON format:
    
    {
      "summary": "Brief summary of the session (2-3 sentences)",
      "topics": ["Topic 1", "Topic 2", ...],
      "action_items": [
        {"description": "Action item 1", "assignee": "coach|client", "priority": "high|medium|low"},
        ...
      ],
      "sentiment": "positive|neutral|negative",
      "key_moments": [
        {"timestamp": "MM:SS", "description": "Description of key moment"},
        ...
      ],
      "coaching_techniques": ["Technique 1", "Technique 2", ...],
      "follow_up_suggestions": ["Suggestion 1", "Suggestion 2", ...]
    }
    
    Focus on being accurate, insightful, and helpful for both the coach and client.
    """
    
    # User prompt contains the transcript and session context
    coach_name = session.get("coach", {}).get("name", "The coach")
    client_name = session.get("client", {}).get("name", "The client")
    session_title = session.get("title", "Coaching session")
    session_goal = session.get("goal", "Not specified")
    
    user_prompt = f"""
    Session Title: {session_title}
    Coach: {coach_name}
    Client: {client_name}
    Session Goal: {session_goal}
    
    Transcript:
    {transcript.get("text", "")}
    
    Please analyze this coaching session transcript and provide insights in the requested JSON format.
    """
    
    return {
        "system": system_prompt.strip(),
        "user": user_prompt.strip(),
    }


def parse_analysis_response(response_text: str) -> Dict[str, Any]:
    """
    Parse OpenAI response into structured analysis.
    
    Args:
        response_text: Text response from OpenAI
        
    Returns:
        Structured analysis dict
    """
    import json
    import re
    
    # Try to extract JSON from response
    try:
        # Look for JSON block in the response
        json_match = re.search(r'```json\s*(.*?)\s*```', response_text, re.DOTALL)
        if json_match:
            json_str = json_match.group(1)
        else:
            # If no code block, try to parse the whole response
            json_str = response_text
        
        # Parse JSON
        analysis = json.loads(json_str)
        
        # Validate required fields
        required_fields = ["summary", "topics", "action_items", "sentiment"]
        for field in required_fields:
            if field not in analysis:
                analysis[field] = [] if field in ["topics", "action_items"] else ""
        
        return analysis
    
    except (json.JSONDecodeError, AttributeError) as e:
        logger.error("Failed to parse analysis response", error=str(e))
        
        # Fallback: return basic structure with error
        return {
            "summary": "Failed to parse analysis response",
            "topics": [],
            "action_items": [],
            "sentiment": "neutral",
            "error": str(e),
            "raw_response": response_text,
        }


def store_analysis(session_id: str, transcript_id: str, analysis: Dict) -> str:
    """
    Store analysis in database.
    
    Args:
        session_id: ID of the session
        transcript_id: ID of the transcript
        analysis: Analysis data
        
    Returns:
        ID of the created analysis
    """
    from bson.objectid import ObjectId
    
    # Create analysis document
    analysis_doc = {
        "_id": ObjectId(),
        "session_id": session_id,
        "transcript_id": transcript_id,
        "summary": analysis.get("summary", ""),
        "topics": analysis.get("topics", []),
        "action_items": analysis.get("action_items", []),
        "sentiment": analysis.get("sentiment", "neutral"),
        "key_moments": analysis.get("key_moments", []),
        "coaching_techniques": analysis.get("coaching_techniques", []),
        "follow_up_suggestions": analysis.get("follow_up_suggestions", []),
        "created_at": time.time(),
    }
    
    # Insert into database
    collection = Database.db.analyses
    collection.insert_one(analysis_doc)
    
    logger.info("Analysis stored", analysis_id=str(analysis_doc["_id"]), session_id=session_id)
    return str(analysis_doc["_id"])


# =====================================================
# Scheduled Tasks
# =====================================================
@celery_app.on_after_configure.connect
def setup_periodic_tasks(sender, **kwargs):
    """Configure periodic tasks."""
    # Daily cleanup task at midnight
    sender.add_periodic_task(
        crontab(hour=0, minute=0),
        cleanup_old_tasks.s(),
        name="cleanup-old-tasks",
    )
    
    # Send reminder emails every hour
    sender.add_periodic_task(
        60 * 60,  # 1 hour
        send_session_reminders.s(),
        name="send-session-reminders",
    )


@celery_app.task(base=BaseTask, name="app.tasks.cleanup_old_tasks")
def cleanup_old_tasks():
    """Clean up old task records."""
    # Implementation would go here
    logger.info("Cleaning up old task records")


@celery_app.task(base=BaseTask, name="app.tasks.send_session_reminders")
def send_session_reminders():
    """Send reminder emails for upcoming sessions."""
    # Implementation would go here
    logger.info("Sending session reminders")


# Make celery_app importable
__all__ = ["celery_app"]
