from app.db.database import SessionLocal
from app.db.models import Generation
from app.schemas.resume import ResumeRecommendation
from pydantic import ValidationError

db = SessionLocal()
gen = db.query(Generation).order_by(Generation.created_at.desc()).first()
try:
    ResumeRecommendation(**gen.resume_json)
    print('Success!')
except ValidationError as e:
    for err in e.errors():
        print(err['loc'], err['msg'], err['type'])
