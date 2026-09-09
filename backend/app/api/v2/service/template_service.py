"""模板业务逻辑。"""
from app.api.v2.utils.template_generator import generate_project_template, generate_attendance_template


def download_template(template_type: str):
    if template_type == "project_base":
        return generate_project_template()
    return generate_attendance_template()