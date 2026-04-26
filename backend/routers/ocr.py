import os
import re
import json
import shutil

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.orm import Session

from backend import crud, database
from backend.models import RoleEnum
from backend.services.pdf_ocr_service import extract_pdf_to_json, get_primary_method
from backend.services.ai_service import analyze_document_with_ai

router = APIRouter(prefix="/ocr", tags=["ocr"])

UPLOADS_PDF_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "uploads", "pdfs"))
UPLOADS_JSON_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "uploads", "json"))


def _clean_amount(raw: str) -> float | None:
    """Nettoie et convertit une chaîne en float."""
    try:
        cleaned = re.sub(r"[^\d.,]", "", raw)
        cleaned = cleaned.replace(",", ".")
        # Si plusieurs points, garder le dernier comme décimal
        parts = cleaned.split(".")
        if len(parts) > 2:
            cleaned = "".join(parts[:-1]) + "." + parts[-1]
        return float(cleaned)
    except Exception:
        return None


def extract_financial_info_locally(json_data: dict, filename: str) -> dict:
    """
    Extraction 100% locale des informations financières depuis le JSON OCR.
    Analyse le texte brut, les tableaux et les champs structurés.
    Retourne: budget, title, department, type, description, requested_by
    """
    # Construire le texte complet
    raw_pages = json_data.get("raw_pages", [])
    full_text = "\n".join(p.get("text", "") for p in raw_pages)

    # Ajouter le contenu des tableaux
    tables_text = ""
    for table in json_data.get("extracted_tables", []):
        for row in table.get("rows", []):
            tables_text += " ".join(str(v) for v in row.values()) + "\n"
    full_text_all = full_text + "\n" + tables_text

    result = {
        "budget": None,
        "title": None,
        "department": None,
        "type": "OTHER_EXPENSE",
        "description": None,
        "requested_by": None,
    }

    # ── 1. EXTRACTION DU MONTANT ─────────────────────────────────────
    # Chercher dans extracted_fields d'abord
    for field in json_data.get("extracted_fields", []):
        if field.get("field_name") in ["budget_total", "montant", "cout", "budget_demande"]:
            try:
                result["budget"] = float(field["field_value"])
                break
            except (ValueError, TypeError):
                pass

    # Patterns regex pour trouver le montant dans le texte brut
    if result["budget"] is None:
        amount_patterns = [
            # Montant avec unité TND/DT explicite
            r"(?:montant|budget|co[uû]t|financement|demande|total)[^\d\n]{0,30}([\d\s]+(?:[.,]\d+)?)\s*(?:TND|DT|dinars?)",
            r"([\d\s]+(?:[.,]\d+)?)\s*(?:TND|DT|dinars?)",
            # Montant général avec des milliers
            r"(?:montant|budget|co[uû]t|financement|demande|total)\s*:?\s*([\d\s]{4,}(?:[.,]\d{1,3})?)",
            # Montant en début de ligne après tiret/deux-points
            r"[:=]\s*([\d\s]{4,}(?:[.,]\d+)?)\s*(?:TND|DT|F|€)?",
        ]
        for pattern in amount_patterns:
            matches = re.findall(pattern, full_text_all, re.IGNORECASE)
            for match in matches:
                raw = match.strip().replace(" ", "")
                amount = _clean_amount(raw)
                if amount and amount > 100:  # Au moins 100 TND
                    result["budget"] = amount
                    break
            if result["budget"] is not None:
                break

    # ── 2. EXTRACTION DU DÉPARTEMENT / INSTITUTION ───────────────────
    dept_patterns = [
        r"(?:département|direction|laboratoire|labo|établissement|faculté|école|institute?|unité)\s*(?:de|d['e]|:)?\s*([A-ZÀÂÉÈÊËÎÏÔÙÛÜ][^\n,;.]{3,60})",
        r"(?:ENIT|FSEGT|IPEIS|ISG|FSJPS|IPEIT|ISET|ENSI|FST|ENSTAB|FSS|FSHST|IPSI|ESST)\b[^\n]*",
        r"(?:présenté par|soumis par|demandeur)\s*:?\s*([A-ZÀÂÉÈÊËÎÏÔÙÛÜ][^\n,;.]{3,60})",
    ]
    for pattern in dept_patterns:
        match = re.search(pattern, full_text_all, re.IGNORECASE)
        if match:
            dept = match.group(0) if match.lastindex is None else match.group(1)
            result["department"] = dept.strip()[:100]
            break

    # Fallback : chercher acronymes connus d'établissements UCAR
    if not result["department"]:
        acronyms = re.findall(r"\b(ENIT|FSEGT|IPEIS|ISG|FSJPS|IPEIT|ISET|ENSI|FST|ENSTAB|FSS|FSHST|IPSI|ESST)\b",
                              full_text_all)
        if acronyms:
            result["department"] = acronyms[0]

    # ── 3. DÉTECTION DU TYPE DE DÉPENSE ─────────────────────────────
    type_keywords = {
        "PUBLIC_MARKET": [r"march[eé] public", r"appel d.offres", r"avis d.appel"],
        "PURCHASE":      [r"achat", r"acquisition", r"commande", r"fourniture"],
        "SALE":          [r"vente", r"cession", r"aliénation"],
        "EVENT_EXPENSE": [r"conf[eé]rence", r"s[eé]minaire", r"colloque", r"forum", r"workshop", r"[eé]v[eé]nement"],
        "LAB_FUNDING":   [r"laboratoire", r"labo\b", r"recherche", r"projet de recherche", r"équipement.*labo"],
    }
    for req_type, keywords in type_keywords.items():
        for kw in keywords:
            if re.search(kw, full_text_all, re.IGNORECASE):
                result["type"] = req_type
                break
        if result["type"] != "OTHER_EXPENSE":
            break

    # ── 4. EXTRACTION DU TITRE ───────────────────────────────────────
    title_patterns = [
        r"(?:objet|sujet|intitulé|titre)\s*:?\s*([^\n]{10,100})",
        r"(?:demande\s+de\s+financement(?:\s+pour)?)\s*:?\s*([^\n]{5,100})",
        r"demande\s+(?:d['e]['']\s*)?([A-Z][^\n]{10,80})",
    ]
    for pattern in title_patterns:
        match = re.search(pattern, full_text_all, re.IGNORECASE)
        if match:
            result["title"] = match.group(1).strip()[:120]
            break

    # Titre de secours basé sur le nom de fichier
    if not result["title"]:
        base = filename.replace(".pdf", "").replace("_", " ").replace("-", " ")
        result["title"] = base[:120]

    # ── 5. EXTRACTION DU DEMANDEUR ───────────────────────────────────
    requester_patterns = [
        r"(?:présenté par|demandeur|soumis par|responsable|signataire)\s*:?\s*([A-ZÀÂÉÈÊËÎÏÔÙÛÜ][a-zA-ZÀ-ÿ\s\.]{5,60})",
        r"(?:M\.|Mme\.|Pr\.|Dr\.)\s+([A-ZÀÂÉÈÊËÎÏÔÙÛÜ][a-zA-ZÀ-ÿ\s]{3,40})",
    ]
    for pattern in requester_patterns:
        match = re.search(pattern, full_text_all, re.IGNORECASE)
        if match:
            result["requested_by"] = match.group(1).strip()[:80]
            break

    # ── 6. GÉNÉRATION DE LA DESCRIPTION ─────────────────────────────
    # Prendre les premières lignes significatives du document comme description
    lines = [l.strip() for l in full_text.split("\n") if len(l.strip()) > 20]
    if lines:
        desc_parts = lines[:4]
        result["description"] = " ".join(desc_parts)[:400]

    print(f"[OCR-LOCAL] Résultat extraction : {result}")
    return result


@router.post("/upload", summary="Upload un PDF et extrait son contenu en JSON")
async def upload_and_extract(
    file: UploadFile = File(...),
    user_id: int = Form(...),
    document_type: str = Form("generic"),
    db: Session = Depends(database.get_db)
):
    """
    Réservé au Secrétaire Général.
    1. Sauvegarde le PDF
    2. Extrait le contenu (PyMuPDF) → JSON sauvegardé sur disque
    3. Analyse locale du JSON pour extraire les données financières
    4. Crée automatiquement une entrée dans la table Gestion Financière
    """
    # Vérification du rôle
    user = crud.get_user_by_id(db, user_id)
    allowed_roles = [RoleEnum.SECRETARY_GENERAL, RoleEnum.FACULTY_ENSTAB, RoleEnum.FACULTY_ADMIN]
    if not user or user.role not in allowed_roles:
        raise HTTPException(status_code=403, detail="Accès non autorisé")

    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Seuls les fichiers PDF sont acceptés")

    # Sauvegarde PDF
    os.makedirs(UPLOADS_PDF_DIR, exist_ok=True)
    os.makedirs(UPLOADS_JSON_DIR, exist_ok=True)

    safe_filename = file.filename.replace(" ", "_")
    pdf_path = os.path.join(UPLOADS_PDF_DIR, safe_filename)

    with open(pdf_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    file_size_kb = round(os.path.getsize(pdf_path) / 1024, 2)

    # Extraction PDF → JSON
    try:
        json_data = extract_pdf_to_json(pdf_path, document_type=document_type)
        extraction_status = "success"
        error_msg = None
    except Exception as e:
        json_data = {
            "metadata": {"filename": safe_filename},
            "summary": {"status": "error"},
            "error": str(e)
        }
        extraction_status = "failed"
        error_msg = str(e)

    # Sauvegarde JSON sur disque
    json_filename = safe_filename.replace(".pdf", ".json")
    json_path = os.path.join(UPLOADS_JSON_DIR, json_filename)
    with open(json_path, "w", encoding="utf-8") as jf:
        json.dump(json_data, jf, ensure_ascii=False, indent=2)

    print(f"[OCR] JSON sauvegardé : {json_path}")

    total_pages = json_data.get("metadata", {}).get("total_pages", 0)
    primary_method = get_primary_method(json_data)

    # Enregistrement document OCR en DB
    ocr_doc = crud.create_ocr_document(
        db=db,
        filename=safe_filename,
        original_size_kb=file_size_kb,
        total_pages=total_pages,
        extraction_method=primary_method,
        document_type=document_type,
        status=extraction_status,
        json_output_path=json_path,
        uploaded_by=user_id,
        error_message=error_msg
    )

    # ─────────────────────────────────────────────────────────────────
    # Analyse IA (OpenRouter) vs Analyse Locale
    # ─────────────────────────────────────────────────────────────────
    financial_request_created = None
    extraction_info = {}
    ai_extraction = {}

    if extraction_status == "success":
        print(f"[OCR] Analyse IA du fichier JSON '{safe_filename}'...")
        ai_extraction = analyze_document_with_ai(json_data)
        
        print(f"[OCR] Analyse locale du fichier JSON '{safe_filename}'...")
        extraction_info = extract_financial_info_locally(json_data, safe_filename)
        
        # Préférer les résultats de l'IA si disponibles et valides
        final_data = extraction_info.copy()
        if "error" not in ai_extraction:
            print("[OCR] Fusion des résultats : Priorité à l'IA")
            final_data.update({
                "budget": ai_extraction.get("amount") or extraction_info.get("budget"),
                "title": ai_extraction.get("title") or extraction_info.get("title"),
                "department": ai_extraction.get("department") or extraction_info.get("department"),
                "type": ai_extraction.get("type") or extraction_info.get("type"),
                "requested_by": ai_extraction.get("requestedBy") or extraction_info.get("requested_by"),
                "description": ai_extraction.get("description") or extraction_info.get("description")
            })

        budget = final_data.get("budget")

        if budget is not None:
            try:
                user_name = user.fullName if user else f"User {user_id}"
                new_req = crud.create_financial_request_from_ocr(
                    db=db,
                    title=final_data.get("title") or f"Demande OCR — {safe_filename}",
                    amount=float(budget),
                    requestedBy=final_data.get("requested_by") or user_name,
                    department=final_data.get("department") or "Inconnu (OCR)",
                    description=final_data.get("description"),
                    request_type=final_data.get("type"),
                    institution_id=user.institution_id if user else None
                )

                financial_request_created = {
                    "id": new_req.id,
                    "title": new_req.title,
                    "amount": new_req.amount,
                    "department": new_req.department,
                    "type": new_req.type.value if new_req.type else None,
                    "description": new_req.description,
                    "requestedBy": new_req.requestedBy,
                    "status": new_req.status.value if new_req.status else "PENDING"
                }
                print(f"[OCR] Demande creee — ID:{new_req.id} | {budget} TND | {new_req.department}")

            except Exception as e:
                print(f"[OCR] Erreur insertion DB: {e}")
                extraction_info["db_error"] = str(e)
        else:
            print(f"[OCR] Aucun montant detecte dans '{safe_filename}'")

        # ─────────────────────────────────────────────────────────────
        # DÉTECTION DU LABORATOIRE + MISE À JOUR DU FINANCEMENT
        # ─────────────────────────────────────────────────────────────
        lab_updated = None
        try:
            from backend.routers.labs import detect_lab_from_text, lab_to_dict

            full_text = " ".join(p.get("text", "") for p in json_data.get("raw_pages", []))
            for table in json_data.get("extracted_tables", []):
                for row in table.get("rows", []):
                    full_text += " " + " ".join(str(v) for v in row.values())

            # For FACULTY_ADMIN/ENSTAB, scope search to user's institution
            inst_id = user.institution_id if user.role in (
                RoleEnum.FACULTY_ADMIN, RoleEnum.FACULTY_ENSTAB
            ) else None

            detected_lab = detect_lab_from_text(full_text, db, institution_id=inst_id)

            # If no lab matched by text but user is faculty, use first lab of their institution
            if detected_lab is None and inst_id:
                from backend.models import Lab
                detected_lab = db.query(Lab).filter(Lab.institution_id == inst_id).first()
                if detected_lab:
                    print(f"[OCR] Fallback: premier lab de l'institution {inst_id} — {detected_lab.code}")

            if detected_lab and extraction_info.get("budget"):
                budget_amount = float(extraction_info["budget"])
                detected_lab.financement_alloue = (detected_lab.financement_alloue or 0) + budget_amount
                db.commit()
                db.refresh(detected_lab)
                lab_updated = lab_to_dict(detected_lab)
                print(f"[OCR] Lab mis a jour : {detected_lab.code} | +{budget_amount} TND")
            elif detected_lab:
                lab_updated = lab_to_dict(detected_lab)
                print(f"[OCR] Lab detecte (sans budget) : {detected_lab.code}")

        except Exception as e:
            print(f"[OCR] Erreur detection lab: {e}")

    return {
        "document": {
            "id": ocr_doc.id,
            "filename": ocr_doc.filename,
            "original_size_kb": ocr_doc.original_size_kb,
            "total_pages": ocr_doc.total_pages,
            "extraction_method": ocr_doc.extraction_method,
            "document_type": ocr_doc.document_type,
            "status": ocr_doc.status,
            "json_output_path": ocr_doc.json_output_path,
            "uploaded_by": ocr_doc.uploaded_by,
            "error_message": ocr_doc.error_message,
            "createdAt": ocr_doc.createdAt.isoformat()
        },
        "json_data": json_data,
        "financial_request": financial_request_created,
        "extraction_info": extraction_info,
        "grok_extraction": ai_extraction, # Alias for frontend compatibility
        "lab_updated": lab_updated
    }


@router.get("/documents", summary="Liste tous les documents OCR traités")
def list_ocr_documents(db: Session = Depends(database.get_db)):
    """Retourne la liste de tous les documents PDF traités par OCR."""
    docs = crud.get_ocr_documents(db)
    result = []
    for d in docs:
        result.append({
            "id": d.id,
            "filename": d.filename,
            "original_size_kb": d.original_size_kb,
            "total_pages": d.total_pages,
            "extraction_method": d.extraction_method,
            "document_type": d.document_type,
            "status": d.status,
            "json_output_path": d.json_output_path,
            "uploaded_by": d.uploaded_by,
            "error_message": d.error_message,
            "createdAt": d.createdAt.isoformat() if d.createdAt else None
        })
    return result


@router.get("/documents/{doc_id}/json", summary="Retourne le JSON extrait d'un document")
def get_document_json(doc_id: int, db: Session = Depends(database.get_db)):
    """Retourne le JSON complet extrait pour un document OCR spécifique."""
    doc = crud.get_ocr_document(db, doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document non trouvé")

    if not os.path.exists(doc.json_output_path):
        raise HTTPException(status_code=404, detail="Fichier JSON introuvable sur le disque")

    with open(doc.json_output_path, "r", encoding="utf-8") as f:
        json_data = json.load(f)

    return {
        "document_id": doc_id,
        "filename": doc.filename,
        "json_data": json_data
    }
