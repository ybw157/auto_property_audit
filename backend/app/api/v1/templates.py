from fastapi import APIRouter
from app.services.template_generator import generate_project_template, generate_attendance_template

router = APIRouter()

@router.get("/templates/download/{template_type}")
def download_template(template_type: str):
    if template_type == "project_base":
        return generate_project_template()
    return generate_attendance_template()
