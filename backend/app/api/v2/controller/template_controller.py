"""模板控制器。"""
from fastapi import APIRouter

from app.api.v2.service.template_service import download_template

router = APIRouter()


@router.get("/templates/{template_type}")
def download_template_endpoint(template_type: str):
    return download_template(template_type)