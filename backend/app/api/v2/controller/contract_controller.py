"""合同文件记录控制器。"""
import os

from fastapi import APIRouter, UploadFile, File, HTTPException, Request
from fastapi.responses import FileResponse

from app.api.v2.core.result import Result
from app.api.v2.service.contract_service import (
    upload_contract,
    list_contracts,
    get_contract,
    update_rules,
    trigger_extract,
    get_extract_status,
    toggle_status,
    delete_contract,
    update_contract,
)
from app.api.v2.core.permissions import get_current_user, is_admin
from app.api.v2.dto.requests import (
    ContractRulesUpdateRequest,
    ContractStatusUpdateRequest,
    ContractUpdateRequest,
)
from app.api.v2.utils.business_type_mapping import (
    get_business_type_mapping,
    get_business_types_for_project,
)


router = APIRouter()


@router.get("/business-types")
def get_business_types(project_name: str = ""):
    if project_name:
        return Result.ok(data=get_business_types_for_project(project_name))
    return Result.ok(data={
        "projects": list(get_business_type_mapping().keys()),
        "mapping": get_business_type_mapping(),
    })


@router.post("/contracts/upload")
async def upload_contract_file(
    request: Request,
    file: UploadFile = File(...),
):
    user = get_current_user(request)
    project_name = user.get("project_name", "")
    # 非管理员强制使用登录账号的项目名，避免文件解析出的项目名与账号不匹配导致列表查不到
    data = upload_contract(
        file=file,
        project_name=project_name,
        force_project_name=not is_admin(user),
    )
    return Result.ok(data=data)


@router.get("/contracts")
def get_contract_list(request: Request, business_type: str = ""):
    """获取合同列表，根据用户角色自动筛选项目。"""
    user = get_current_user(request)

    if not is_admin(user):
        project_name = user.get("project_name", "")
    else:
        project_name = ""

    data = list_contracts(project_name, business_type)
    return Result.ok(data=data)


@router.get("/contracts/{contract_id}")
def get_contract_detail(contract_id: int):
    data = get_contract(contract_id)
    return Result.ok(data=data)


@router.get("/contracts/{contract_id}/download")
def download_contract(contract_id: int):
    contract = get_contract(contract_id)
    file_path = contract.get("storage_path", "")
    if not file_path or not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="文件不存在")
    data = FileResponse(file_path, filename=contract.get("original_name", "contract"))
    return Result.ok(data=data)


@router.put("/contracts/{contract_id}")
async def update_contract_record(
    request: Request,
    contract_id: int,
    body: ContractUpdateRequest,
):
    user = get_current_user(request)
    fields = {k: v for k, v in body.model_dump().items() if v is not None}
    # 非管理员不允许把合同挂到别的项目下，否则保存后自己反而查不到
    if not is_admin(user):
        fields["project_name"] = user.get("project_name", "")
    data = update_contract(contract_id, **fields)
    return Result.ok(data=data, message="合同更新成功")


@router.put("/contracts/{contract_id}/rules")
async def update_contract_rules(
    request: Request,
    contract_id: int,
    body: ContractRulesUpdateRequest,
):
    get_current_user(request)
    data = update_rules(contract_id, body.rules)
    return Result.ok(data=data)


@router.put("/contracts/{contract_id}/status")
async def update_contract_status(
    request: Request,
    contract_id: int,
    body: ContractStatusUpdateRequest,
):
    get_current_user(request)
    data = toggle_status(contract_id, body.is_active)
    return Result.ok(data=data)


@router.delete("/contracts/{contract_id}")
async def remove_contract(request: Request, contract_id: int):
    get_current_user(request)
    data = delete_contract(contract_id)
    return Result.ok(data=data)


@router.post("/contracts/{contract_id}/extract")
async def trigger_contract_extract(request: Request, contract_id: int):
    get_current_user(request)
    data = trigger_extract(contract_id)
    return Result.ok(data=data)


@router.get("/contracts/{contract_id}/extract-status")
def get_contract_extract_status(contract_id: int):
    return get_extract_status(contract_id)