import streamlit as st
import pandas as pd
import json
import plotly.express as px
import requests
import urllib.request
import re
import os
import streamlit.components.v1 as components
from dotenv import load_dotenv
load_dotenv()

@st.cache_data(ttl=86400)  # Cache for 24 hours
def fetch_the_global_averages():
    """Scrape THE website to compute real global averages from 2000+ universities."""
    try:
        url = "https://www.timeshighereducation.com/world-university-rankings/latest/world-ranking"
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        html = urllib.request.urlopen(req, timeout=120).read().decode('utf-8')
        m = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html, re.DOTALL)
        if not m:
            return None
        next_data = json.loads(m.group(1))
        
        # Find all university entries recursively
        def find_unis(obj):
            results = []
            if isinstance(obj, dict):
                if 'name' in obj and 'scores_teaching' in obj:
                    results.append(obj)
                for v in obj.values():
                    results.extend(find_unis(v))
            elif isinstance(obj, list):
                for item in obj:
                    results.extend(find_unis(item))
            return results
        
        unis = find_unis(next_data)
        # De-duplicate
        seen = set()
        unique = []
        for u in unis:
            n = u.get('name')
            if n and n not in seen:
                seen.add(n)
                unique.append(u)
        
        def safe_float(val):
            try: return float(val)
            except: return None
        
        scores = {'teaching': [], 'research': [], 'citations': [], 'industry': [], 'international': []}
        for u in unique:
            for key, field in [('teaching','scores_teaching'), ('research','scores_research'),
                               ('citations','scores_citations'), ('industry','scores_industry_income'),
                               ('international','scores_international_outlook')]:
                v = safe_float(u.get(field))
                if v is not None:
                    scores[key].append(v)
        
        return {
            'total': len(unique),
            'valid': len(scores['teaching']),
            'teaching': sum(scores['teaching'])/len(scores['teaching']) if scores['teaching'] else 0,
            'research_env': sum(scores['research'])/len(scores['research']) if scores['research'] else 0,
            'research_quality': sum(scores['citations'])/len(scores['citations']) if scores['citations'] else 0,
            'industry': sum(scores['industry'])/len(scores['industry']) if scores['industry'] else 0,
            'international': sum(scores['international'])/len(scores['international']) if scores['international'] else 0,
        }
    except Exception as e:
        return None

# AI Service Configurations (OpenRouter)
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_API_URL = os.getenv("OPENROUTER_API_URL", "https://openrouter.ai/api/v1/chat/completions")

# Configuration
st.set_page_config(
    page_title="UCAR Strategic Governance Dashboard",
    layout="wide",
    initial_sidebar_state="expanded"
)

BACKEND_URL = "http://127.0.0.1:8000"

if 'token' not in st.session_state:
    st.session_state.token = None
if 'user' not in st.session_state:
    st.session_state.user = None

if st.session_state.user is None:
    st.title("UCAR Authentication Gateway")

    st.markdown("Please log in to access the governance dashboards.")
    col1, col2, col3 = st.columns([1,2,1])
    with col2:
        with st.form("login_form"):
            email = st.text_input("Email (president@ucar.tn / sg@ucar.tn)")
            password = st.text_input("Password (admin123)", type="password")
            submitted = st.form_submit_button("Log In", use_container_width=True)
            if submitted:
                try:
                    res = requests.post(f"{BACKEND_URL}/auth/login", json={"email": email, "password": password})
                    if res.status_code == 200:
                        data = res.json()
                        st.session_state.token = data['token']
                        st.session_state.user = data['user']
                        st.rerun()
                    else:
                        st.error("Invalid credentials.")
                except Exception as e:
                    st.error("Could not connect to the backend server. Make sure it is running.")
    st.stop()

# Top/Sidebar Actions for Logged in Users
st.sidebar.markdown(f"**Logged in as:** {st.session_state.user['fullName']}")
st.sidebar.markdown(f"**Role:** {st.session_state.user['role']}")
if st.sidebar.button("Logout"):
    st.session_state.token = None
    st.session_state.user = None
    st.rerun()

# ------------- SECRETARY GENERAL DASHBOARD -------------
if st.session_state.user['role'] == "SECRETARY_GENERAL":
    st.title(" Tableau de Bord  Secrtaire Gnral")
    st.markdown("Gestion des demandes financires et traitement des documents PDF.")

    sg_tab1, sg_tab2 = st.tabs([" Gestion Financire", " Traitement OCR / Documents"])

    # 
    # ONGLET 1  GESTION FINANCIRE
    # 
    with sg_tab1:
        try:
            res = requests.get(f"{BACKEND_URL}/financial-requests")
            if res.status_code == 200:
                reqs = res.json()
            else:
                reqs = []
                st.error("Failed to load requests.")
        except Exception as e:
            reqs = []
            st.error(f"Backend unreachable: {e}")

        df_reqs = pd.DataFrame(reqs)

        if not df_reqs.empty:
            pending_count = len(df_reqs[df_reqs['status'] == 'PENDING'])
            approved_count = len(df_reqs[df_reqs['status'] == 'APPROVED'])
            rejected_count = len(df_reqs[df_reqs['status'] == 'REJECTED'])
            pending_sum = df_reqs[df_reqs['status'] == 'PENDING']['amount'].sum()

            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Pending Requests", pending_count)
            c2.metric("Approved", approved_count)
            c3.metric("Rejected", rejected_count)
            c4.metric("Pending Value", f"{pending_sum:,.2f} TND")

            st.markdown("---")

            # Filters
            col_f1, col_f2 = st.columns(2)
            target_status = col_f1.selectbox("Filter by Status", ["All", "PENDING", "APPROVED", "REJECTED"], index=1)
            target_type = col_f2.selectbox("Filter by Type", ["All"] + list(df_reqs['type'].unique()))

            filtered_reqs = df_reqs.copy()
            if target_status != "All":
                filtered_reqs = filtered_reqs[filtered_reqs['status'] == target_status]
            if target_type != "All":
                filtered_reqs = filtered_reqs[filtered_reqs['type'] == target_type]

            disp_df = filtered_reqs[['id', 'createdAt', 'title', 'type', 'department', 'amount', 'status']]
            if 'createdAt' in disp_df.columns:
                disp_df = disp_df.copy()
                disp_df['createdAt'] = pd.to_datetime(disp_df['createdAt']).dt.strftime('%Y-%m-%d %H:%M')

            st.dataframe(disp_df, hide_index=True)

            st.markdown("### Action Panel")
            pending_list = df_reqs[df_reqs['status'] == 'PENDING']['id'].tolist()

            if pending_list:
                selected_req = st.selectbox("Select Pending Request ID to process", pending_list)

                if selected_req:
                    req_data = df_reqs[df_reqs['id'] == selected_req].iloc[0]
                    with st.expander(" View Request Details", expanded=True):
                        st.write(f"**Title:** {req_data['title']}")
                        st.write(f"**Description:** {req_data['description']}")
                        st.write(f"**Amount:** {req_data['amount']} {req_data['currency']}")
                        st.write(f"**Requesting Department:** {req_data['department']} (by {req_data.get('requestedBy', 'Unknown')})")
                        st.write(f"**Type:** {req_data['type']}")

                    comment = st.text_area("Decision Note / Comment (Optional)")

                    c_app, c_rej, _ = st.columns([1, 1, 4])
                    with c_app:
                        if st.button(" Approve", type="primary"):
                            try:
                                r = requests.post(f"{BACKEND_URL}/financial-requests/{selected_req}/approve",
                                                  json={"decisionNote": comment, "userId": st.session_state.user['id']})
                                if r.status_code == 200:
                                    st.success("Request Approved!")
                                    st.rerun()
                                else:
                                    st.error(r.json().get('detail', 'Error'))
                            except Exception as e:
                                st.error(e)
                    with c_rej:
                        if st.button(" Reject"):
                            try:
                                r = requests.post(f"{BACKEND_URL}/financial-requests/{selected_req}/reject",
                                                  json={"decisionNote": comment, "userId": st.session_state.user['id']})
                                if r.status_code == 200:
                                    st.success("Request Rejected!")
                                    st.rerun()
                                else:
                                    st.error(r.json().get('detail', 'Error'))
                            except Exception as e:
                                st.error(e)
            else:
                st.success("No pending actions at the moment.")
        else:
            st.info("No financial requests found in the system.")

    # 
    # ONGLET 2  OCR / TRAITEMENT DOCUMENTS PDF
    # 
    with sg_tab2:
        st.markdown("###  Extraction PDF  JSON")
        st.markdown(
            "Uploadez un fichier PDF (rapport, budget, relev acadmique). "
            "Le systme extrait automatiquement le texte, les tableaux et les champs structurs "
            "et gnre un **JSON prt  l'emploi** sauvegard dans `uploads/json/`."
        )

        #  SECTION A : Upload 
        with st.container():
            st.markdown("####  Uploader un nouveau document")

            col_up1, col_up2 = st.columns([3, 1])
            with col_up1:
                uploaded_pdf = st.file_uploader(
                    "Slectionner un fichier PDF",
                    type=["pdf"],
                    key="ocr_pdf_uploader",
                    label_visibility="collapsed"
                )
            with col_up2:
                doc_type_choice = st.selectbox(
                    "Type de document",
                    ["generic", "finance", "academic", "timetable", "research"],
                    key="ocr_doc_type"
                )

            if uploaded_pdf is not None:
                file_size_kb = round(len(uploaded_pdf.getvalue()) / 1024, 2)
                st.info(f" **{uploaded_pdf.name}**  {file_size_kb} KB")

                if st.button(" Extraire le JSON", type="primary", key="btn_ocr_extract"):
                    with st.spinner(f"Traitement de  {uploaded_pdf.name}  en cours"):
                        try:
                            resp = requests.post(
                                f"{BACKEND_URL}/ocr/upload",
                                files={"file": (uploaded_pdf.name, uploaded_pdf.getvalue(), "application/pdf")},
                                data={
                                    "user_id": str(st.session_state.user['id']),
                                    "document_type": doc_type_choice
                                },
                                timeout=120
                            )
                            if resp.status_code == 200:
                                result = resp.json()
                                doc_meta = result["document"]
                                json_data = result["json_data"]
                                summary = json_data.get("summary", {})
                                metadata = json_data.get("metadata", {})
                                financial_req = result.get("financial_request")
                                grok_info = result.get("grok_extraction", {})

                                st.success(" Extraction russie !")

                                #  BANDEAU DEMANDE FINANCIRE CRE 
                                if financial_req:
                                    st.markdown("""
                                    <div style="background: linear-gradient(135deg, #065f46, #047857);
                                                border-radius: 12px; padding: 20px; margin: 12px 0;
                                                border-left: 5px solid #10b981; color: white;">
                                        <div style="font-size:1.1rem; font-weight:700; margin-bottom:10px;">
                                             Demande Financire ajoute  Gestion Financire
                                        </div>
                                    """, unsafe_allow_html=True)

                                    fa, fb, fc = st.columns(3)
                                    fa.metric(" Montant", f"{financial_req['amount']:,.0f} TND")
                                    fb.metric(" Dpartement", financial_req.get('department', 'N/A'))
                                    fc.metric(" Type", financial_req.get('type', 'N/A'))

                                    st.markdown(f"""
                                    <div style="background:rgba(255,255,255,0.1); border-radius:8px;
                                                padding:14px; margin-top:10px; color:white;">
                                        <b> Titre :</b> {financial_req.get('title', 'N/A')}<br><br>
                                        <b> Description :</b> {financial_req.get('description', 'Non renseigne')}<br><br>
                                        <b> Demandeur :</b> {financial_req.get('requestedBy', 'N/A')}
                                        &nbsp;&nbsp;|&nbsp;&nbsp;
                                        <b> Statut :</b> {financial_req.get('status', 'PENDING')}
                                        &nbsp;&nbsp;|&nbsp;&nbsp;
                                        <b>#ID :</b> {financial_req.get('id', '?')}
                                    </div>
                                    """, unsafe_allow_html=True)
                                    st.markdown("</div>", unsafe_allow_html=True)
                                    st.info(" Allez dans l'onglet ** Gestion Financire** pour voir et traiter cette demande.")
                                elif grok_info.get("grok_error"):
                                    st.warning(f" Grok n'a pas pu extraire de donnes financires : {grok_info['grok_error']}")
                                else:
                                    st.warning(" Aucun montant dtect dans ce document. Aucune demande financire cre.")

                                st.markdown("---")

                                # Mtriques rsum
                                m1, m2, m3, m4 = st.columns(4)
                                m1.metric("Pages traites", doc_meta['total_pages'])
                                m2.metric("Caractres extraits", f"{summary.get('total_text_chars', 0):,}")
                                m3.metric("Tables dtectes", summary.get('total_tables_found', 0))
                                m4.metric("Champs structurs", summary.get('total_fields_extracted', 0))

                                st.markdown(f"**Mthode principale :** `{doc_meta['extraction_method']}`")
                                st.markdown(f"**Mthodes utilises :** `{', '.join(metadata.get('extraction_methods', []))}`")
                                st.markdown(f"**Confiance moyenne :** `{summary.get('avg_confidence', 0):.0%}`")
                                st.markdown(f"**JSON sauvegard dans :** `{doc_meta['json_output_path']}`")

                                # Champs extraits
                                extracted_fields = json_data.get("extracted_fields", [])
                                if extracted_fields:
                                    st.markdown("####  Champs / KPIs dtects")
                                    fields_df = pd.DataFrame(extracted_fields)
                                    st.dataframe(fields_df, hide_index=True)

                                # Tables
                                extracted_tables = json_data.get("extracted_tables", [])
                                if extracted_tables:
                                    st.markdown(f"####  Tables extraites ({len(extracted_tables)})")
                                    for t in extracted_tables[:5]:
                                        with st.expander(f"Table  Page {t['page']} (mthode : {t['extraction_method']})"):
                                            rows = t.get("rows", [])
                                            if rows:
                                                st.dataframe(pd.DataFrame(rows), hide_index=True)

                                # Texte brut par page
                                raw_pages = json_data.get("raw_pages", [])
                                if raw_pages:
                                    with st.expander(" Texte brut extrait (par page)"):
                                        for page_data in raw_pages[:10]:
                                            st.markdown(f"**Page {page_data['page']}** "
                                                        f" Confiance: `{page_data['confidence']:.0%}` "
                                                        f" Mthode: `{page_data['method']}`")
                                            st.text_area(
                                                f"Texte page {page_data['page']}",
                                                value=page_data['text'][:2000],
                                                height=120,
                                                key=f"ocr_text_p{page_data['page']}_{doc_meta['id']}",
                                                disabled=True
                                            )

                                # Tlchargement JSON
                                st.download_button(
                                    label=" Tlcharger le JSON complet",
                                    data=json.dumps(json_data, ensure_ascii=False, indent=2),
                                    file_name=uploaded_pdf.name.replace(".pdf", "_extracted.json"),
                                    mime="application/json",
                                    key="ocr_download_btn"
                                )
                            elif resp.status_code == 403:
                                st.error(" Accs refus. Rserv au Secrtaire Gnral.")
                            else:
                                st.error(f"Erreur lors de l'extraction : {resp.text}")
                        except requests.exceptions.ConnectionError:
                            st.error(" Impossible de joindre le backend. Vrifiez qu'il est en cours d'excution sur le port 8000.")
                        except Exception as e:
                            st.error(f"Erreur inattendue : {e}")

        st.markdown("---")

        #  SECTION B : Historique des documents traits 
        st.markdown("####  Historique des documents traits")

        if st.button(" Rafrachir l'historique", key="btn_refresh_ocr_history"):
            st.rerun()

        try:
            hist_res = requests.get(f"{BACKEND_URL}/ocr/documents", timeout=10)
            if hist_res.status_code == 200:
                ocr_history = hist_res.json()
                if ocr_history:
                    hist_df = pd.DataFrame(ocr_history)
                    hist_df['createdAt'] = pd.to_datetime(hist_df['createdAt']).dt.strftime('%Y-%m-%d %H:%M')
                    display_cols = ['id', 'filename', 'original_size_kb', 'total_pages',
                                    'extraction_method', 'document_type', 'status', 'createdAt']
                    st.dataframe(
                        hist_df[display_cols].rename(columns={
                            'id': 'ID', 'filename': 'Fichier', 'original_size_kb': 'Taille (KB)',
                            'total_pages': 'Pages', 'extraction_method': 'Mthode',
                            'document_type': 'Type', 'status': 'Statut', 'createdAt': 'Date'
                        }),
                        hide_index=True
                    )

                    # Voir JSON d'un document de l'historique
                    st.markdown("####  Consulter le JSON d'un document")
                    doc_ids = [d['id'] for d in ocr_history]
                    doc_labels = [f"[{d['id']}] {d['filename']}" for d in ocr_history]
                    selected_hist_label = st.selectbox("Slectionner un document", doc_labels, key="sel_hist_doc")
                    selected_hist_id = doc_ids[doc_labels.index(selected_hist_label)]

                    if st.button(" Afficher le JSON extrait", key="btn_show_hist_json"):
                        try:
                            json_resp = requests.get(f"{BACKEND_URL}/ocr/documents/{selected_hist_id}/json", timeout=30)
                            if json_resp.status_code == 200:
                                hist_json = json_resp.json()["json_data"]
                                hist_summary = hist_json.get("summary", {})

                                s1, s2, s3 = st.columns(3)
                                s1.metric("Pages", hist_json.get("metadata", {}).get("total_pages", "N/A"))
                                s2.metric("Champs extraits", hist_summary.get("total_fields_extracted", 0))
                                s3.metric("Tables", hist_summary.get("total_tables_found", 0))

                                fields = hist_json.get("extracted_fields", [])
                                if fields:
                                    st.markdown("**Champs dtects :**")
                                    st.dataframe(pd.DataFrame(fields), hide_index=True)

                                with st.expander(" JSON complet"):
                                    st.json(hist_json)

                                st.download_button(
                                    label=" Tlcharger ce JSON",
                                    data=json.dumps(hist_json, ensure_ascii=False, indent=2),
                                    file_name=f"doc_{selected_hist_id}_extracted.json",
                                    mime="application/json",
                                    key="hist_download_btn"
                                )
                            else:
                                st.error(f"Erreur : {json_resp.text}")
                        except Exception as e:
                            st.error(f"Erreur lors du chargement du JSON : {e}")
                else:
                    st.info("Aucun document OCR trait pour l'instant. Uploadez votre premier PDF ci-dessus.")
            else:
                st.error("Impossible de charger l'historique.")
        except Exception as e:
            st.warning(f"Backend non joignable : {e}")

    st.stop()


# ------------- ENSTAB FACULTY DASHBOARD -------------
if st.session_state.user['role'] in ("FACULTY_ENSTAB", "FACULTY_ADMIN"):
    st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;600;700;800&display=swap');
    html, body, [class*="css"] { font-family: 'Inter', sans-serif; }
    .enstab-header {
        background: linear-gradient(135deg, #1e3a5f 0%, #2563eb 50%, #1d4ed8 100%);
        border-radius: 16px; padding: 28px 32px; margin-bottom: 24px; color: white;
    }
    .enstab-header h1 { color: white !important; font-size: 1.8rem; margin:0; }
    .enstab-header p { color: rgba(255,255,255,0.85); margin: 6px 0 0 0; font-size: 1rem; }
    .lab-card {
        background: white; border-radius: 12px; padding: 20px; margin: 8px 0;
        border: 1px solid #e2e8f0; border-left: 5px solid #2563eb;
        box-shadow: 0 2px 8px rgba(0,0,0,0.06); transition: transform 0.2s;
    }
    .lab-card:hover { transform: translateY(-2px); box-shadow: 0 8px 20px rgba(0,0,0,0.1); }
    .lab-title { font-size: 1rem; font-weight: 700; color: #1e3a5f; margin-bottom: 4px; }
    .lab-code { font-size: 0.75rem; background: #dbeafe; color: #1d4ed8;
                padding: 2px 8px; border-radius: 20px; font-weight: 600; display: inline-block; }
    .kpi-mini { text-align: center; padding: 12px; background: #f8fafc;
                border-radius: 8px; border: 1px solid #e2e8f0; }
    .kpi-mini .val { font-size: 1.4rem; font-weight: 800; color: #1e3a5f; }
    .kpi-mini .lbl { font-size: 0.72rem; color: #64748b; font-weight: 500; }
    .prog-bar-bg { background: #e2e8f0; border-radius: 8px; height: 10px; margin-top: 6px; }
    .prog-bar-fg { background: linear-gradient(90deg, #2563eb, #3b82f6); border-radius: 8px; height: 10px; }
    </style>
    """, unsafe_allow_html=True)

    st.markdown("""
    <div class="enstab-header">
        <h1> Plateforme ENSTAB  Gestion des Laboratoires</h1>
        <p>Suivi du financement, des effectifs et de la recherche des laboratoires de l'ENSTAB</p>
    </div>
    """, unsafe_allow_html=True)

    BACKEND_URL_E = "http://127.0.0.1:8000"

    def load_enstab_labs():
        """Charge les donnes fraches des labs depuis le backend."""
        try:
            r = requests.get(f"{BACKEND_URL_E}/labs/enstab", timeout=10)
            return r.json() if r.status_code == 200 else []
        except Exception:
            return []

    tab_labs, tab_charts, tab_ocr = st.tabs([
        " Laboratoires & Financement",
        " Analyses & Statistiques",
        " Import OCR / Documents"
    ])

    #  ONGLET 1 : LABORATOIRES 
    with tab_labs:
        col_refresh, _ = st.columns([1, 5])
        with col_refresh:
            if st.button("Rafraichir les donnees", key="btn_refresh_labs"):
                st.rerun()
        enstab_labs = load_enstab_labs()
        if enstab_labs:
            df_labs = pd.DataFrame(enstab_labs)

            # KPIs globaux
            st.markdown("###  Indicateurs Globaux ENSTAB")
            g1, g2, g3, g4, g5 = st.columns(5)
            g1.metric(" Laboratoires", len(df_labs))
            g2.metric(" tudiants", int(df_labs['nb_etudiants'].sum()))
            g3.metric(" Enseignants", int(df_labs['nb_enseignants'].sum()))
            g4.metric(" Financement Total", f"{df_labs['financement_total'].sum():,.0f} TND")
            g5.metric(" Publications", int(df_labs['publications'].sum()))

            st.markdown("---")
            st.markdown("###  Dtail par Laboratoire")

            for _, lab in df_labs.iterrows():
                taux = lab['taux_utilisation']
                bar_color = "#22c55e" if taux < 70 else "#f59e0b" if taux < 90 else "#ef4444"
                domaines_html = " ".join([f'<span style="background:#dbeafe;color:#1d4ed8;padding:2px 8px;border-radius:12px;font-size:0.72rem;margin:2px;">{d}</span>' for d in lab.get('domaines', [])])

                st.markdown(f"""
                <div class="lab-card">
                    <div style="display:flex; justify-content:space-between; align-items:flex-start; flex-wrap:wrap;">
                        <div>
                            <div class="lab-title">{lab['name']}</div>
                            <span class="lab-code">{lab['code']}</span>
                            <span style="font-size:0.8rem; color:#64748b; margin-left:10px;">Dir. {lab.get('director','N/A')}</span>
                        </div>
                    </div>
                    <div style="margin:10px 0 4px 0;">{domaines_html}</div>
                    <p style="color:#475569;font-size:0.85rem;margin:8px 0;">{lab.get('description','')}</p>
                    <div style="display:grid;grid-template-columns:repeat(5,1fr);gap:8px;margin-top:12px;">
                        <div class="kpi-mini"><div class="val">{lab['nb_etudiants']}</div><div class="lbl">tudiants</div></div>
                        <div class="kpi-mini"><div class="val">{lab['nb_enseignants']}</div><div class="lbl">Enseignants</div></div>
                        <div class="kpi-mini"><div class="val">{lab['projets_actifs']}</div><div class="lbl">Projets actifs</div></div>
                        <div class="kpi-mini"><div class="val">{lab['publications']}</div><div class="lbl">Publications</div></div>
                        <div class="kpi-mini"><div class="val" style="color:{bar_color};">{taux}%</div><div class="lbl">Budget utilis</div></div>
                    </div>
                    <div style="margin-top:10px;">
                        <div style="font-size:0.78rem;color:#64748b;margin-bottom:3px;">
                            Budget: <b>{lab['financement_alloue']:,.0f} TND</b> allou / <b>{lab['financement_total']:,.0f} TND</b> total
                        </div>
                        <div class="prog-bar-bg"><div class="prog-bar-fg" style="width:{min(taux,100)}%;background:linear-gradient(90deg,{bar_color},{bar_color}99);"></div></div>
                    </div>
                </div>
                """, unsafe_allow_html=True)
        else:
            st.warning("Impossible de charger les laboratoires. Vrifiez que le backend est en cours d'excution.")

    #  ONGLET 2 : ANALYSES 
    with tab_charts:
        enstab_labs = load_enstab_labs()
        if enstab_labs:
            df_labs = pd.DataFrame(enstab_labs)
            st.markdown("###  Analyses Comparatives des Laboratoires")

            col1, col2 = st.columns(2)
            with col1:
                fig_fin = px.bar(df_labs.sort_values('financement_total', ascending=False),
                                 x='code', y=['financement_total', 'financement_alloue'],
                                 title=" Financement Total vs Allou (TND)",
                                 barmode='group',
                                 color_discrete_sequence=['#2563eb', '#22c55e'],
                                 labels={'value': 'TND', 'code': 'Laboratoire'})
                fig_fin.update_layout(plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)")
                st.plotly_chart(fig_fin, use_container_width=True)

            with col2:
                fig_eff = px.bar(df_labs.sort_values('nb_etudiants', ascending=False),
                                 x='code', y=['nb_etudiants', 'nb_enseignants'],
                                 title=" Effectifs par Laboratoire",
                                 barmode='group',
                                 color_discrete_sequence=['#7c3aed', '#f59e0b'],
                                 labels={'value': 'Personnes', 'code': 'Laboratoire'})
                fig_eff.update_layout(plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)")
                st.plotly_chart(fig_eff, use_container_width=True)

            col3, col4 = st.columns(2)
            with col3:
                fig_pub = px.bar(df_labs.sort_values('publications', ascending=False),
                                 x='code', y='publications',
                                 title=" Publications Scientifiques",
                                 color='publications', color_continuous_scale='Blues',
                                 labels={'publications': 'Publications', 'code': 'Laboratoire'})
                fig_pub.update_layout(plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)")
                st.plotly_chart(fig_pub, use_container_width=True)

            with col4:
                fig_taux = px.bar(df_labs.sort_values('taux_utilisation', ascending=False),
                                  x='code', y='taux_utilisation',
                                  title=" Taux d'Utilisation du Budget (%)",
                                  color='taux_utilisation',
                                  color_continuous_scale=['#22c55e', '#f59e0b', '#ef4444'],
                                  range_color=[0, 100],
                                  labels={'taux_utilisation': '% utilis', 'code': 'Laboratoire'})
                fig_taux.update_layout(plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)")
                st.plotly_chart(fig_taux, use_container_width=True)

            # Scatter plot : ratio enseignants/tudiants vs publications
            st.markdown("###  Corrlation : Ratio Encadrement vs Recherche")
            df_labs['ratio_encadrement'] = df_labs.apply(
                lambda r: round(r['nb_etudiants'] / max(r['nb_enseignants'], 1), 1), axis=1)
            fig_sc = px.scatter(df_labs, x='ratio_encadrement', y='publications',
                                size='projets_actifs', color='code', hover_name='name',
                                title="Ratio tudiants/Enseignant vs Publications (taille = projets actifs)",
                                labels={'ratio_encadrement': 'tudiants par enseignant', 'publications': 'Publications'})
            fig_sc.update_layout(plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)")
            st.plotly_chart(fig_sc, use_container_width=True)

        else:
            st.warning("Aucune donne disponible pour les analyses.")

    #  ONGLET 3 : OCR 
    with tab_ocr:
        st.markdown("###  Import de Documents  Dtection Automatique du Laboratoire")
        st.markdown(
            "Uploadez un document PDF (demande de financement, rapport, appel d'offres). "
            "Le systme extrait les donnes, **dtecte le laboratoire** et **met  jour son financement** automatiquement."
        )

        col_up, col_type = st.columns([3, 1])
        with col_up:
            enstab_pdf = st.file_uploader("Slectionner un fichier PDF",
                                          type=["pdf"], key="enstab_ocr_uploader",
                                          label_visibility="collapsed")
        with col_type:
            enstab_doc_type = st.selectbox("Type", ["finance", "generic", "research", "academic"],
                                           key="enstab_doc_type")

        if enstab_pdf is not None:
            kb = round(len(enstab_pdf.getvalue()) / 1024, 2)
            st.info(f" **{enstab_pdf.name}**  {kb} KB")

            if st.button(" Analyser & Dtecter le Laboratoire", type="primary", key="enstab_ocr_btn"):
                with st.spinner("Extraction et analyse en cours"):
                    try:
                        resp = requests.post(
                            f"{BACKEND_URL_E}/ocr/upload",
                            files={"file": (enstab_pdf.name, enstab_pdf.getvalue(), "application/pdf")},
                            data={"user_id": str(st.session_state.user['id']), "document_type": enstab_doc_type},
                            timeout=120
                        )
                        if resp.status_code == 200:
                            result = resp.json()
                            json_data = result["json_data"]
                            fin_req = result.get("financial_request")
                            lab_updated = result.get("lab_updated")

                            st.success(" Document analys avec succs !")

                            #  LABORATOIRE DTECT & MIS  JOUR 
                            if lab_updated:
                                old_alloue = lab_updated['financement_alloue'] - (fin_req['amount'] if fin_req else 0)
                                new_alloue = lab_updated['financement_alloue']
                                taux = lab_updated['taux_utilisation']
                                bar_color = "#22c55e" if taux < 70 else "#f59e0b" if taux < 90 else "#ef4444"

                                st.markdown(f"""
                                <div style="background:linear-gradient(135deg,#1e3a5f,#1d4ed8);
                                            border-radius:14px;padding:22px;color:white;margin:14px 0;
                                            border-left:6px solid #60a5fa;">
                                    <div style="font-size:1.15rem;font-weight:800;margin-bottom:12px;">
                                         Laboratoire dtect & mis  jour : {lab_updated['name']}
                                    </div>
                                    <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-bottom:14px;">
                                        <div style="background:rgba(255,255,255,0.12);border-radius:8px;padding:10px;text-align:center;">
                                            <div style="font-size:1.3rem;font-weight:800;">{lab_updated['code']}</div>
                                            <div style="font-size:0.72rem;opacity:0.8;">Code Laboratoire</div>
                                        </div>
                                        <div style="background:rgba(255,255,255,0.12);border-radius:8px;padding:10px;text-align:center;">
                                            <div style="font-size:1.3rem;font-weight:800;">{lab_updated['nb_etudiants']}</div>
                                            <div style="font-size:0.72rem;opacity:0.8;">tudiants</div>
                                        </div>
                                        <div style="background:rgba(255,255,255,0.12);border-radius:8px;padding:10px;text-align:center;">
                                            <div style="font-size:1.3rem;font-weight:800;">{lab_updated['nb_enseignants']}</div>
                                            <div style="font-size:0.72rem;opacity:0.8;">Enseignants</div>
                                        </div>
                                        <div style="background:rgba(255,255,255,0.12);border-radius:8px;padding:10px;text-align:center;">
                                            <div style="font-size:1.3rem;font-weight:800;">{lab_updated['projets_actifs']}</div>
                                            <div style="font-size:0.72rem;opacity:0.8;">Projets actifs</div>
                                        </div>
                                    </div>
                                    <div style="background:rgba(255,255,255,0.1);border-radius:10px;padding:14px;">
                                        <div style="font-size:0.82rem;opacity:0.85;margin-bottom:6px;">
                                            Dir. <b>{lab_updated.get('director','N/A')}</b>
                                        </div>
                                        <div style="font-size:0.9rem;margin-bottom:8px;">
                                             Financement allou mis  jour :
                                            <b>{new_alloue:,.0f} TND</b>
                                            sur <b>{lab_updated['financement_total']:,.0f} TND</b> total
                                        </div>
                                        <div style="background:rgba(255,255,255,0.2);border-radius:6px;height:12px;">
                                            <div style="background:{bar_color};border-radius:6px;height:12px;width:{min(taux,100):.0f}%;"></div>
                                        </div>
                                        <div style="font-size:0.78rem;margin-top:4px;opacity:0.85;">
                                            Taux d'utilisation : <b>{taux}%</b>
                                        </div>
                                    </div>
                                </div>
                                """, unsafe_allow_html=True)

                                if fin_req:
                                    st.success(f" +{fin_req['amount']:,.0f} TND ajouts au financement du laboratoire **{lab_updated['code']}**")

                            else:
                                st.warning(" Aucun laboratoire ENSTAB dtect dans ce document.")

                            #  DEMANDE FINANCIRE CRE 
                            if fin_req:
                                st.markdown(f"""
                                <div style="background:linear-gradient(135deg,#065f46,#047857);
                                            border-radius:12px;padding:20px;color:white;margin:14px 0;
                                            border-left:6px solid #34d399;">
                                    <div style="font-size:1.05rem;font-weight:700;margin-bottom:10px;">
                                         Demande Financire ajoute  Gestion Financire
                                    </div>
                                    <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px;margin-bottom:10px;">
                                        <div style="background:rgba(255,255,255,0.12);border-radius:8px;padding:8px;text-align:center;">
                                            <div style="font-size:1.2rem;font-weight:800;">{fin_req.get('amount',0):,.0f} TND</div>
                                            <div style="font-size:0.72rem;opacity:0.8;">Montant</div>
                                        </div>
                                        <div style="background:rgba(255,255,255,0.12);border-radius:8px;padding:8px;text-align:center;">
                                            <div style="font-size:0.95rem;font-weight:700;">{fin_req.get('type','N/A')}</div>
                                            <div style="font-size:0.72rem;opacity:0.8;">Type</div>
                                        </div>
                                        <div style="background:rgba(255,255,255,0.12);border-radius:8px;padding:8px;text-align:center;">
                                            <div style="font-size:0.95rem;font-weight:700;">{fin_req.get('status','PENDING')}</div>
                                            <div style="font-size:0.72rem;opacity:0.8;">Statut</div>
                                        </div>
                                    </div>
                                    <div style="font-size:0.85rem;opacity:0.95;line-height:1.7;">
                                        <b>Titre :</b> {fin_req.get('title','N/A')}<br>
                                        <b>Dpartement :</b> {fin_req.get('department','N/A')} &nbsp;|&nbsp;
                                        <b>ID :</b> #{fin_req.get('id','?')}
                                    </div>
                                </div>
                                """, unsafe_allow_html=True)
                            else:
                                st.warning(" Aucun montant financier dtect dans ce document.")

                            #  MTRIQUES D'EXTRACTION 
                            st.markdown("---")
                            doc_meta = result["document"]
                            summary = json_data.get("summary", {})
                            m1, m2, m3, m4 = st.columns(4)
                            m1.metric(" Pages", doc_meta['total_pages'])
                            m2.metric(" Caractres", f"{summary.get('total_text_chars',0):,}")
                            m3.metric(" Tables", summary.get('total_tables_found', 0))
                            m4.metric(" Champs", summary.get('total_fields_extracted', 0))

                            fields = json_data.get("extracted_fields", [])
                            if fields:
                                st.markdown("####  Champs dtects dans le document")
                                st.dataframe(pd.DataFrame(fields), hide_index=True)

                            raw_pages = json_data.get("raw_pages", [])
                            if raw_pages:
                                with st.expander(" Texte brut extrait"):
                                    for pg in raw_pages[:5]:
                                        st.text_area(f"Page {pg['page']}", value=pg['text'][:1500],
                                                     height=100, disabled=True,
                                                     key=f"enstab_pg_{pg['page']}")

                            # Sauvegarder le JSON pour tlchargement
                            st.session_state["last_ocr_json"] = json.dumps(json_data, ensure_ascii=False, indent=2)
                            st.session_state["last_ocr_filename"] = enstab_pdf.name

                            # Forcer le rechargement pour afficher les labs mis  jour
                            if lab_updated:
                                st.info(" Rechargement des donnes du laboratoire en cours...")
                                import time; time.sleep(1)
                                st.rerun()

                        elif resp.status_code == 403:
                            st.error(" Accs refus.")
                        else:
                            st.error(f"Erreur backend : {resp.text}")
                    except requests.exceptions.ConnectionError:
                        st.error(" Backend non joignable. Dmarrez le backend sur le port 8000.")
                    except Exception as e:
                        st.error(f"Erreur : {e}")

            # Bouton de tlchargement persistant
            if "last_ocr_json" in st.session_state:
                st.download_button(
                    label=" Tlcharger le dernier JSON extrait",
                    data=st.session_state["last_ocr_json"],
                    file_name=st.session_state.get("last_ocr_filename", "extracted.pdf").replace(".pdf", "_extracted.json"),
                    mime="application/json", key="enstab_dl_btn_persist"
                )

    st.stop()
# ------------- PRESIDENT DASHBOARD -------------
# Execution only reaches here if logged in as PRESIDENT

# Premium Custom CSS for an enterprise-level platform
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;600;700&display=swap');
    
    html, body, [class*="css"] {
        font-family: 'Inter', sans-serif;
        background-color: #f4f6f9;
    }
    
    .stApp {
        background-color: #f4f6f9;
        color: #1e293b;
    }
    
    /* KPI Cards Styling */
    .kpi-card {
        background-color: #ffffff;
        border-radius: 6px;
        padding: 24px;
        margin: 12px 0;
        border: 1px solid #e2e8f0;
        border-left: 4px solid #0f172a;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05), 0 2px 4px -1px rgba(0, 0, 0, 0.03);
        transition: transform 0.2s ease, box-shadow 0.2s ease;
    }
    
    .kpi-card:hover {
        transform: translateY(-2px);
        box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.08), 0 4px 6px -2px rgba(0, 0, 0, 0.04);
    }
    
    .kpi-title {
        font-size: 0.85rem;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.05em;
        color: #64748b;
        margin-bottom: 8px;
    }
    
    .kpi-value {
        font-size: 2rem;
        font-weight: 700;
        color: #0f172a;
    }
    
    /* Headers and Text */
    h1, h2, h3 {
        color: #0f172a !important;
        font-weight: 700 !important;
    }
    
    p {
        color: #334155;
    }
    
    /* Alerts Styling */
    .alert-card {
        background-color: #ffffff;
        border-radius: 6px;
        padding: 16px 24px;
        margin: 12px 0;
        border: 1px solid #e2e8f0;
        box-shadow: 0 1px 3px 0 rgba(0, 0, 0, 0.1);
    }
    
    .alert-danger {
        border-left: 4px solid #dc2626;
        background-color: #fef2f2;
    }
    
    .alert-warning {
        border-left: 4px solid #f59e0b;
        background-color: #fffbeb;
    }
    
    .alert-title {
        font-weight: 600;
        color: #0f172a;
        margin-bottom: 4px;
    }
    
    .alert-text {
        font-size: 0.9rem;
        color: #475569;
    }
    
    /* Tabs Customization */
    .stTabs [data-baseweb="tab-list"] {
        gap: 24px;
    }

    .stTabs [data-baseweb="tab"] {
        height: 50px;
        white-space: pre-wrap;
        background-color: transparent;
        border-radius: 4px 4px 0px 0px;
        gap: 1px;
        padding-top: 10px;
        padding-bottom: 10px;
        color: #64748b;
    }

    .stTabs [aria-selected="true"] {
        color: #0f172a;
        font-weight: 600;
    }
</style>
""", unsafe_allow_html=True)

@st.cache_data
def load_data():
    with open('ucar_strategic_data.json', 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    institutions = []
    for inst in data['institutions']:
        inst_data = {
            'id': inst['id'],
            'name': inst['name'],
            'code': inst['code'],
            'type': inst['type'],
            'city': inst['city'],
            'employability_rate': inst['employability']['employability_rate'],
            'avg_months_to_employment': inst['employability']['avg_months_to_employment'],
            'recruitment_needs': ", ".join(inst['employability']['recruitment_needs']),
            'accreditation_status': inst['accreditation']['status'],
            'total_programs': inst['accreditation']['total_programs'],
            'programs_at_risk': inst['accreditation']['programs_at_risk'],
            'accreditation_details': inst['accreditation']['details'],
            'research_score': inst['research']['score'],
            'publications': inst['research']['publications'],
            'active_projects': inst['research']['active_projects'],
            'success_rate': inst['academic']['success_rate'],
            'repetition_rate': inst['academic']['repetition_rate'],
            'professor_competencies': ", ".join(inst['competencies']['professor_competencies']),
            'strong_domains': ", ".join(inst['competencies']['strong_domains']),
            'weak_domains': ", ".join(inst['competencies']['weak_domains'])
        }
        institutions.append(inst_data)
    
    df = pd.DataFrame(institutions)
    
    # Generate Alerts and Risk Levels
    alerts = []
    
    for i, row in df.iterrows():
        inst_alerts = []
        if row['employability_rate'] < 0.70:
            inst_alerts.append({"Institution": row['name'], "Risk type": "Employability", "Cause": f"Rate at {row['employability_rate']:.0%}", "Suggested action": "Review employer partnerships and curriculum alignment.", "Level": "danger"})
        if row['accreditation_status'] == 'at_risk' or row['accreditation_status'] == 'not_accredited':
            inst_alerts.append({"Institution": row['name'], "Risk type": "Accreditation", "Cause": f"Status is {row['accreditation_status']}", "Suggested action": "Commission an immediate program compliance audit.", "Level": "danger"})
        if row['research_score'] < 75:
            inst_alerts.append({"Institution": row['name'], "Risk type": "Research", "Cause": f"Score at {row['research_score']}", "Suggested action": "Deploy targeted research incentives for faculty.", "Level": "warning"})
        if row['success_rate'] < 0.70:
            inst_alerts.append({"Institution": row['name'], "Risk type": "Academic", "Cause": f"Success at {row['success_rate']:.0%}", "Suggested action": "Enhance pedagogical support and intervention mechanisms.", "Level": "warning"})
        if row['repetition_rate'] > 0.15:
            inst_alerts.append({"Institution": row['name'], "Risk type": "Repetition", "Cause": f"Repetition at {row['repetition_rate']:.0%}", "Suggested action": "Implement standardized tutoring and mentoring programs.", "Level": "warning"})
            
        alerts.extend(inst_alerts)
        
        if len(inst_alerts) == 0:
            df.at[i, 'risk_level'] = 'Low'
        elif len(inst_alerts) <= 2:
            df.at[i, 'risk_level'] = 'Medium'
        else:
            df.at[i, 'risk_level'] = 'High'
            
    alerts_df = pd.DataFrame(alerts)
    
    return df, alerts_df, data['global_metrics']

df, alerts_df, global_metrics = load_data()

@st.cache_data
def load_ranking_data():
    try:
        with open('extracted_ranking_data.json', 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return None

ranking_data = load_ranking_data()

# ---------------- Sidebar Filters ----------------
st.sidebar.markdown("### Strategic Parameters")

selected_institution = st.sidebar.selectbox("Filter by Institution", ["All"] + list(df['name'].unique()))
selected_risk = st.sidebar.multiselect("Filter by Risk Level", ["Low", "Medium", "High"], default=["Low", "Medium", "High"])
selected_accreditation = st.sidebar.multiselect("Filter by Accreditation", ["accredited", "at_risk", "not_accredited"], default=["accredited", "at_risk", "not_accredited"])

# Apply Filters
filtered_df = df.copy()

if selected_institution != "All":
    filtered_df = filtered_df[filtered_df['name'] == selected_institution]

filtered_df = filtered_df[filtered_df['risk_level'].isin(selected_risk)]
filtered_df = filtered_df[filtered_df['accreditation_status'].isin(selected_accreditation)]

filtered_alerts = alerts_df if selected_institution == "All" else alerts_df[alerts_df['Institution'] == selected_institution]

st.title("UCAR Strategic Governance Dashboard")
st.markdown("Advanced analytics and performance monitoring across the University of Carthage institutional network.")

# ---------------- Tabs Layout ----------------
tabs = st.tabs([
    "Executive Overview", 
    "Institutional Analytics", 
    "Accreditation Status", 
    "Research & Faculty", 
    "Employment & Success", 
    "System Alerts", 
    "AI Strategic Assistant",
    "Institution Deep Dive",
    "Global THE Rankings",
    " Ranking Advisor",
    "Ranking Simulator"
])

def create_kpi_card(title, value):
    return f"""
    <div class="kpi-card">
        <div class="kpi-title">{title}</div>
        <div class="kpi-value">{value}</div>
    </div>
    """

# --- OVERVIEW TAB ---
with tabs[0]:
    if len(filtered_df) == 0:
        st.warning("No institutions match the configured environmental parameters.")
    else:
        st.markdown("### Global Performance Indicators")
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            st.markdown(create_kpi_card("Employability Rate", f"{filtered_df['employability_rate'].mean():.1%}"), unsafe_allow_html=True)
            st.markdown(create_kpi_card("Accredited Programs", f"{filtered_df['total_programs'].sum()}"), unsafe_allow_html=True)
        with c2:
            st.markdown(create_kpi_card("Avg Time to Employ", f"{filtered_df['avg_months_to_employment'].mean():.1f} mo"), unsafe_allow_html=True)
            st.markdown(create_kpi_card("Programs at Risk", f"{filtered_df['programs_at_risk'].sum()}"), unsafe_allow_html=True)
        with c3:
            st.markdown(create_kpi_card("Total Publications", f"{filtered_df['publications'].sum()}"), unsafe_allow_html=True)
            st.markdown(create_kpi_card("Avg Success Rate", f"{filtered_df['success_rate'].mean():.1%}"), unsafe_allow_html=True)
        with c4:
            st.markdown(create_kpi_card("Active Research Proj.", f"{filtered_df['active_projects'].sum()}"), unsafe_allow_html=True)
            st.markdown(create_kpi_card("Avg Repetition", f"{filtered_df['repetition_rate'].mean():.1%}"), unsafe_allow_html=True)
        
        st.markdown("---")
        st.markdown("### Visual Analytics")
        col1, col2 = st.columns(2)
        
        with col1:
            fig1 = px.bar(filtered_df, x='code', y='employability_rate', title="Taux d'Insertion Professionnelle par tablissement", color='employability_rate', color_continuous_scale='blues')
            fig1.update_layout(plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)")
            st.plotly_chart(fig1, use_container_width=True)
            
        with col2:
            fig2 = px.bar(filtered_df, x='code', y='research_score', title="Score Numrique de Performance en Recherche", color='research_score', color_continuous_scale='teal')
            fig2.update_layout(plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)")
            st.plotly_chart(fig2, use_container_width=True)

# --- INSTITUTIONS TABLE TAB ---
with tabs[1]:
    st.markdown("### Institutional Comparison Matrix")
    display_cols = ['name', 'type', 'city', 'employability_rate', 'accreditation_status', 'research_score', 'success_rate', 'repetition_rate', 'risk_level']
    st.dataframe(
        filtered_df[display_cols].style.format({
            'employability_rate': '{:.1%}',
            'success_rate': '{:.1%}',
            'repetition_rate': '{:.1%}'
        }),
        hide_index=True
    )

# --- ACCREDITATION TAB ---
with tabs[2]:
    st.markdown("### Accreditation Distribution")
    col1, col2 = st.columns(2)
    with col1:
        acc_counts = df['accreditation_status'].value_counts().reset_index()
        acc_counts.columns = ['Status', 'Count']
        fig3 = px.pie(acc_counts, values='Count', names='Status', title="Rpartition des Statuts d'Accrditation du Rseau", color='Status', color_discrete_map={'accredited':'#10b981', 'at_risk':'#f59e0b', 'not_accredited':'#ef4444'})
        fig3.update_layout(plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)")
        st.plotly_chart(fig3, use_container_width=True)
    with col2:
        st.markdown("### Vulnerable Programs Distribution")
        at_risk = filtered_df[filtered_df['programs_at_risk'] > 0][['code', 'programs_at_risk']]
        if not at_risk.empty:
            fig_risk = px.bar(at_risk, x='code', y='programs_at_risk', title="Distribution des Programmes Non-Conformes", color_discrete_sequence=['#ef4444'])
            fig_risk.update_layout(plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)")
            st.plotly_chart(fig_risk, use_container_width=True)
        else:
            st.success("System displays normal parameters. No programs are currently flagged as non-compliant.")

# --- RESEARCH & COMPETENCIES TAB ---
with tabs[3]:
    st.markdown("### Research Output & Faculty Capabilities")
    col1, col2 = st.columns(2)
    with col1:
        fig4 = px.bar(filtered_df.sort_values('publications', ascending=False), x='code', y='publications', title="Volumtrie des Publications Scientifiques", color_discrete_sequence=['#0f172a'])
        fig4.update_layout(plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)")
        st.plotly_chart(fig4, use_container_width=True)
    with col2:
        st.markdown("**Faculty Competency Evaluation:**")
        for i, row in filtered_df.iterrows():
            with st.expander(f"Capabilities Review: {row['code']}"):
                st.write(f"**Disciplinary Composition:** {row['professor_competencies']}")
                st.write(f"**Pillars of Excellence:** {row['strong_domains']}")
                st.write(f"**Identified Deficits:** {row['weak_domains']}")

# --- EMPLOYABILITY TAB ---
with tabs[4]:
    st.markdown("### Academic Efficiency Correlation")
    fig5 = px.scatter(
        filtered_df, 
        x='repetition_rate', 
        y='success_rate', 
        color='risk_level',
        size='employability_rate',
        hover_name='code',
        title="Matrice Diagnostique : Russite Acadmique vs Redoublement (Taille = Employabilit)"
    )
    fig5.update_layout(plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)")
    st.plotly_chart(fig5, use_container_width=True)

# --- ALERTS TAB ---
with tabs[5]:
    st.markdown("### Automated Governance Diagnostics")
    if filtered_alerts.empty:
        st.success("The network configuration meets all defined operational thresholds.")
    else:
        for idx, alert in filtered_alerts.iterrows():
            css_class = "alert-danger" if alert['Level'] == 'danger' else "alert-warning"
            st.markdown(f"""
            <div class="alert-card {css_class}">
                <div class="alert-title">{alert['Institution']} | Flag: {alert['Risk type']}</div>
                <div class="alert-text">
                    <strong>Diagnostic:</strong> {alert['Cause']}<br>
                    <strong>Recommended Directive:</strong> {alert['Suggested action']}
                </div>
            </div>
            """, unsafe_allow_html=True)

# --- AI ASSISTANT TAB ---
with tabs[6]:
    st.markdown("### UCAR Smart Query Engine")
    st.markdown("Ask any question about UCAR institutions in natural language — or use the interactive chatbot below.")

    components.iframe(
        "https://hacathon-ucar.vercel.app",
        height=600,
        scrolling=True
    )

    st.markdown("---")
    st.markdown("### Strategic Integration AI")
    st.markdown("Execute intelligence queries against UCAR strategic metrics mapping for immediate analysis.")
    
    question = st.text_input("Enter strategic parameter query or objective:", placeholder="E.g., Detail the faculty capability gaps associated with high-risk accreditations.")
    
    # Helper function to call AI via OpenRouter
    def ask_ai(prompt):
        # We supply the loaded data directly as context
        context_data = df[['name', 'employability_rate', 'accreditation_status', 'programs_at_risk', 'research_score', 'success_rate', 'repetition_rate', 'recruitment_needs', 'professor_competencies']].to_dict(orient="records")
        system_prompt = (
            "You are an executive-level strategic AI analyst for the Board of the University of Carthage (UCAR). "
            "Deliver uncompromising, highly professional, direct, and data-backed diagnostics. "
            f"Reference Context JSON Matrix: {json.dumps(context_data)}"
        )
        
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {OPENROUTER_API_KEY}"
        }
        
        payload = {
            "model": "google/gemini-2.0-flash-001",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.2
        }
        
        try:
            response = requests.post(OPENROUTER_API_URL, headers=headers, json=payload)
            response.raise_for_status()
            result = response.json()
            return result['choices'][0]['message']['content']
        except Exception as e:
            return f"System Integration Error: {str(e)}"

    if st.button("Execute Diagnostic Query"):
        if question:
            with st.spinner("Processing network variables..."):
                answer = ask_ai(question)
                st.info(answer)
        else:
            st.warning("Query missing. Input parameter required.")

# --- INSTITUTION DETAILS TAB ---
with tabs[7]:
    st.markdown("### Organizational Deep Dive")
    detail_inst = st.selectbox("Select Target Institution Profile", df['code'].tolist())
    inst_data = df[df['code'] == detail_inst].iloc[0]
    
    st.markdown(f"#### Profile: {inst_data['name']}")
    
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("##### Framework & Core Indicators")
        st.write(f"**Status Registry:** {inst_data['accreditation_status'].upper()}")
        st.write(f"**Regulatory Remarks:** {inst_data['accreditation_details']}")
        st.write(f"**Aggregated Success Coefficient:** {inst_data['success_rate']:.1%}")
        st.write(f"**Retention Failure Rate:** {inst_data['repetition_rate']:.1%}")
        st.write(f"**Faculty Competencies Listed:** {inst_data['professor_competencies']}")
        st.write(f"**Organizational Strengths:** {inst_data['strong_domains']}")
        st.write(f"**Identified Operational Lags:** {inst_data['weak_domains']}")
        
    with c2:
        st.markdown("##### Market Integration & R&D")
        st.write(f"**Market Placement Index:** {inst_data['employability_rate']:.1%}")
        st.write(f"**Placement Velocity:** {inst_data['avg_months_to_employment']} months")
        st.write(f"**Strategic HR Deficits:** {inst_data['recruitment_needs']}")
        st.write(f"**Quantitative R&D Score:** {inst_data['research_score']}")
        st.write(f"**Peer-Reviewed Publications:** {inst_data['publications']}")
        st.write(f"**Active Sector Projects:** {inst_data['active_projects']}")

# --- GLOBAL RANKINGS TAB ---
with tabs[8]:
    st.markdown("### Times Higher Education (THE) - Global Standings")
    if ranking_data and "rankings" in ranking_data:
        world_data = ranking_data["rankings"].get("world", {})
        scores = world_data.get("scores", {})
        
        scraped_at = ranking_data.get("scraped_at", "N/A")
        
        st.markdown(f"**Last Sync:** {scraped_at} | [View Original THE Source](https://www.timeshighereducation.com/world-university-rankings/university-carthage)")
        
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            st.markdown(create_kpi_card("World Rank", str(world_data.get('rank', 'N/A'))), unsafe_allow_html=True)
            st.markdown(create_kpi_card("Total Students", "32,944"), unsafe_allow_html=True)
        with c2:
            st.markdown(create_kpi_card("Teaching Score", str(scores.get('teaching', 'N/A'))), unsafe_allow_html=True)
            st.markdown(create_kpi_card("Students per Staff", "10.6"), unsafe_allow_html=True)
        with c3:
            st.markdown(create_kpi_card("Research Quality", str(scores.get('research_quality', 'N/A'))), unsafe_allow_html=True)
            st.markdown(create_kpi_card("Intl. Students", "1%"), unsafe_allow_html=True)
        with c4:
            st.markdown(create_kpi_card("Industry Score", str(scores.get('industry', 'N/A'))), unsafe_allow_html=True)
            st.markdown(create_kpi_card("Female : Male", "64 : 36"), unsafe_allow_html=True)
            
        st.markdown("---")
        
        # --- DYNAMIC SUBJECT CATEGORIES ---
        st.markdown("#### Subject Rankings")
        cat_cols = st.columns(4)
        cats = [
            ("Business & Econ.", "business_economics"), 
            ("Computer Science", "computer_science"), 
            ("Engineering", "engineering"), 
            ("Life Sciences", "life_sciences")
        ]
        for i, (cat_label, cat_key) in enumerate(cats):
            with cat_cols[i]:
                cat_data = ranking_data["rankings"].get(cat_key, {})
                cat_rank = cat_data.get('rank', 'N/A')
                st.markdown(
                    f"""
                    <div style="background:#1E1E2E; padding:15px; border-radius:8px; border:1px solid rgba(255,255,255,0.1); text-align:center; margin-bottom:10px;">
                        <h5 style="margin:0; color:#E0E0E0; font-size:14px;">{cat_label}</h5>
                        <h3 style="margin:5px 0 0 0; color:#3b82f6;">{cat_rank}</h3>
                    </div>
                    """, 
                    unsafe_allow_html=True
                )
                
        if "ai_insights" in ranking_data:
            insights = ranking_data["ai_insights"]
            st.markdown("###  Grok Weekly Diagnostics")
            st.info(f"**Action Recommande (Grok) :** {insights.get('recommended_priority', '')}")
            st.success(f"**Point Fort :** Meilleure performance en **{insights.get('strongest_category', '')}**")
            st.warning(f"**Alerte :** Le score le plus faible est **{insights.get('weakest_score', '')}**")
            st.markdown(f" **Amlioration la plus rapide :** {insights.get('fastest_improving', '')}")

        st.markdown("---")
        
        # --- Interactive Historical Trend ---
        st.markdown("#### Ranking positions 2020 to 2026")
        
        years = ['2020', '2021', '2022', '2023', '2024', '2025', '2026']
        
        # Build trend safely from the new JSON format
        trend_data = world_data.get("trend", [])
        teaching_trend = [t.get("teaching_score") for t in trend_data]
        if not teaching_trend or len(teaching_trend) < 7:
             teaching_trend = [19.6, 19.2, 19.8, 19.0, 23.8, 25.0, scores.get('teaching', 24.8)]

        metrics_history = {
            "Teaching": teaching_trend,
            "Research Environment": [8.3, 8.8, 9.8, 9.8, 9.9, 9.9, scores.get('research_environment', 10.2)],
            "Research Quality": [19.4, 20.0, 19.4, 19.1, 31.2, 32.1, scores.get('research_quality', 32.2)],
            "Industry": [34.7, 33.9, 36.4, 38.3, 20.7, 32.8, scores.get('industry', 34.7)],
            "International Outlook": [43.3, 44.1, 43.9, 44.1, 44.1, 43.9, scores.get('international_outlook', 43.9)]
        }
        
        # Two-column layout matching the website screenshot
        col_list, col_graph = st.columns([1, 4])
        
        with col_list:
            selected_metric = st.radio(
                "Select Metric",
                list(metrics_history.keys()),
                label_visibility="collapsed"
            )
            # Display current value of selected metric
            curr_val = metrics_history[selected_metric][-1]
            st.markdown(f"<div style='font-size: 1.2rem; font-weight: bold; color: #6366f1; margin-top: 10px;'>{curr_val}</div>", unsafe_allow_html=True)
            
        with col_graph:
            # Plotly Line Chart matching THE site visuals exactly
            fig_trend = px.line(
                x=years, 
                y=metrics_history[selected_metric], 
                markers=True,
                text=metrics_history[selected_metric]  # Puts exact values on the dots
            )
            
            # Exact THE visual styling
            fig_trend.update_traces(
                textposition="top center",
                textfont=dict(color="#6b7280", size=13),
                line_color='#8494ff',  # Specific THE purple/blue line
                marker=dict(size=8, color='#8494ff'),
                line_width=2
            )
            fig_trend.update_layout(
                height=300,
                plot_bgcolor="rgba(0,0,0,0)", 
                paper_bgcolor="rgba(0,0,0,0)",
                margin=dict(l=0, r=30, t=30, b=40),
                yaxis=dict(
                    showgrid=False,
                    zeroline=False,
                    showline=False,
                    side='right', # Y-axis on the right side
                    tickfont=dict(color='#9ca3af'),
                ),
                xaxis=dict(
                    showgrid=False,
                    zeroline=False,
                    showline=False,
                    tickfont=dict(color='#6b7280', size=13)
                )
            )
            
            # Bottom right subtitle label
            fig_trend.add_annotation(
                text=f"Breakdown via year: <span style='color:#8494ff'>{selected_metric}</span>",
                xref="paper", yref="paper",
                x=1, y=-0.25,
                showarrow=False,
                font=dict(color='#6b7280', size=11)
            )
            
            st.plotly_chart(fig_trend, use_container_width=True)
            
        st.markdown("---")
        
        st.markdown("#### Ranked Subject Areas")
        subjects = ranking_data.get('subjects', [])
        if subjects:
            for sub in subjects:
                st.markdown(f"- {sub}")
    else:
        st.warning("Ranking data file not found. Ensure the extractor script has run.")

# --- RANKING ADVISOR TAB ---
with tabs[9]:
    st.markdown("### Strategic Ranking Improvement Advisor")
    st.markdown("Data-driven intelligence to ascend global university rankings.")
    
    # BONUS: UCAR Global Score
    global_score = (df['employability_rate'].mean() * 100 * 0.3 + 
                    df['research_score'].mean() * 0.4 + 
                    df['success_rate'].mean() * 100 * 0.3)
    
    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown(create_kpi_card("UCAR Global Score", f"{global_score:.1f}/100"), unsafe_allow_html=True)
    with c2:
        st.markdown(create_kpi_card("Improvement Potential", " +120 Ranks possible"), unsafe_allow_html=True)
    with c3:
        st.markdown(create_kpi_card("Current Trajectory", " Stable to Positive"), unsafe_allow_html=True)

    if st.button("Generate Strategy", type="primary"):
        with st.spinner("Analyzing institutional data and computing strategic insights..."):
            import time
            time.sleep(1.5) # Simulate processing
            
            # Rule-based calculations
            blockers = []
            priority_scores = []
            
            for _, row in df.iterrows():
                issues = 0
                if row['employability_rate'] < 0.70:
                    blockers.append(f"**{row['code']}**: Critical employability ({row['employability_rate']:.0%})")
                    issues += 2
                if row['accreditation_status'] in ['at_risk', 'not_accredited']:
                    blockers.append(f"**{row['code']}**: Major ranking risk (Accreditation: {row['accreditation_status']})")
                    issues += 3
                if row['research_score'] < 75:
                    blockers.append(f"**{row['code']}**: Weak research performance ({row['research_score']})")
                    issues += 2
                if row['success_rate'] < 0.70:
                    blockers.append(f"**{row['code']}**: Academic weakness (Success: {row['success_rate']:.0%})")
                    issues += 1
                if row['repetition_rate'] > 0.15:
                    blockers.append(f"**{row['code']}**: Inefficiency (Repetition: {row['repetition_rate']:.0%})")
                    issues += 1
                
                priority_scores.append({"Institution": row['name'], "Code": row['code'], "Issues Score": issues})
            
            priority_df = pd.DataFrame(priority_scores).sort_values(by="Issues Score", ascending=False)
            top_priority = priority_df.head(3)
            
            st.markdown("---")
            
            st.markdown("####  Diagnosis")
            st.info("The network shows strong baseline health but suffers from inconsistent research volumes and isolated accreditation vulnerabilities. Addressing these disparities can rapidly elevate UCAR's global position. Action must prioritize fast-tracking structural improvements in high-risk faculties.")

            col1, col2 = st.columns(2)
            with col1:
                st.markdown("####  Ranking Blockers")
                if blockers:
                    for b in blockers[:5]:
                        st.error(b)
                else:
                    st.success("No major blockers detected.")
                    
            with col2:
                st.markdown("####  Priority Institutions")
                st.write("Target these 3 institutions for immediate structural action:")
                for _, p in top_priority.iterrows():
                    st.warning(f"**{p['Code']}** - {p['Institution']} (Severity Score: {p['Issues Score']})")

            st.markdown("####  Recommended Actions")
            action_data = [
                {"Action": "Fast-Track Accreditation Audit", "Target": "FLAH & FSB", "Expected Impact": "High", "Priority": " High"},
                {"Action": "Industry Partnership Expansion", "Target": "FLAH & FSB (Employability)", "Expected Impact": "Medium", "Priority": " High"},
                {"Action": "Research Grant Injection", "Target": "ISG (Research)", "Expected Impact": "High", "Priority": " Medium"},
                {"Action": "Mentorship & Tutoring Standard", "Target": "FLAH (Repetition)", "Expected Impact": "Low", "Priority": " Low"}
            ]
            st.table(pd.DataFrame(action_data))
            
            c_wins, c_long = st.columns(2)
            with c_wins:
                st.markdown("####  Quick Wins (6 months)")
                st.markdown("""
                - **Syllabus Overhaul:** Immediate curriculum update for at-risk master programs (ISG).
                - **Research Bootcamps:** Cross-institution seminars (ENSI + FSB/ISG) to stimulate publications.
                - **Internship Portals:** Launch single-point student placement portal to raise employability figures.
                """)
            with c_long:
                st.markdown("####  Long-term Strategy (2 years)")
                st.markdown("""
                - **Global Accreditations:** Migrate all primary faculties to international standards (AACSB, CTI).
                - **Digital Transformation:** Establish a centralized digital humanities hub for FLAH.
                - **Holistic R&D Hubs:** Fund cross-disciplinary research clusters emphasizing modern tech and sciences.
                """)
                
            st.markdown("---")
            st.markdown("####  Employability vs. Research Comparison")
            st.markdown("Visual assessment highlighting worst-performing entities against structural goals.")
            
            # Prepare normalized data for bar chart
            bar_df = df[['code', 'employability_rate', 'research_score', 'risk_level']].copy()
            bar_df['Employability (%)'] = bar_df['employability_rate'] * 100
            bar_df.rename(columns={'research_score': 'Research Score'}, inplace=True)
            
            fig_bar = px.bar(
                bar_df, 
                x="code", 
                y=["Employability (%)", "Research Score"], 
                barmode="group",
                title="Employability Rate vs. Research Score by Institution",
                color_discrete_sequence=["#3b82f6", "#10b981"]
            )
            fig_bar.update_layout(
                plot_bgcolor="rgba(0,0,0,0)", 
                paper_bgcolor="rgba(0,0,0,0)",
                legend_title_text='Metric'
            )
            st.plotly_chart(fig_bar, use_container_width=True)


# --- RANKING SIMULATOR TAB ---
with tabs[10]:
    import plotly.graph_objects as go
    
    st.markdown("### Ranking Simulator (THE Scores)")
    st.markdown("Simulate the impact of strategic improvements on the Times Higher Education (THE) global ranking.")
    
    # Extract baseline scores dynamically (Defaulting to Computer Science as per initial specification)
    baseline_cat = ranking_data.get("rankings", {}).get("computer_science", {}) if ranking_data else {}
    base_scores = baseline_cat.get("scores", {})
    base_teaching = float(base_scores.get("teaching", 20.1))
    base_research_env = float(base_scores.get("research_environment", 9.7))
    base_research_q = float(base_scores.get("research_quality", 42.1))
    base_industry = float(base_scores.get("industry", 36.9))
    base_international = float(base_scores.get("international_outlook", 39.7))
    
    # SECTION 1: Current Scores Display
    st.markdown("#### Current Baseline (University of Carthage)")
    st_cols = st.columns(5)
    with st_cols[0]:
        st.markdown(create_kpi_card("Teaching", f"{base_teaching:.1f}"), unsafe_allow_html=True)
    with st_cols[1]:
        st.markdown(create_kpi_card("Research Env", f"{base_research_env:.1f}"), unsafe_allow_html=True)
    with st_cols[2]:
        st.markdown(create_kpi_card("Research Quality", f"{base_research_q:.1f}"), unsafe_allow_html=True)
    with st_cols[3]:
        st.markdown(create_kpi_card("Industry", f"{base_industry:.1f}"), unsafe_allow_html=True)
    with st_cols[4]:
        st.markdown(create_kpi_card("International", f"{base_international:.1f}"), unsafe_allow_html=True)
        
    st.markdown("---")
    
    # SECTION 2: Interactive Sliders
    st.markdown("#### Adjust Scores to Simulate New Rank")
    
    col1, col2 = st.columns([1, 1])
    
    with col1:
        sim_teaching = st.slider("Teaching Score", min_value=base_teaching, max_value=100.0, value=base_teaching, step=0.1, key="sim_teaching")
        sim_research_env = st.slider("Research Environment", min_value=base_research_env, max_value=100.0, value=base_research_env, step=0.1, key="sim_research_env")
        sim_research_q = st.slider("Research Quality", min_value=base_research_q, max_value=100.0, value=base_research_q, step=0.1, key="sim_research_q")
        sim_industry = st.slider("Industry Score", min_value=base_industry, max_value=100.0, value=base_industry, step=0.1, key="sim_industry")
        sim_international = st.slider("International Outlook", min_value=base_international, max_value=100.0, value=base_international, step=0.1, key="sim_international")
        
        # Calculate improvement deltas
        d_teaching = sim_teaching - base_teaching
        d_research_env = sim_research_env - base_research_env
        d_research_q = sim_research_q - base_research_q
        d_industry = sim_industry - base_industry
        d_international = sim_international - base_international
        total_delta = d_teaching + d_research_env + d_research_q + d_industry + d_international
        
    with col2:
        # SECTION 6: Radar Chart Comparison
        categories = ['Teaching', 'Research Env', 'Research Quality', 'Industry', 'International']
        current_vals = [base_teaching, base_research_env, base_research_q, base_industry, base_international]
        simulated_vals = [sim_teaching, sim_research_env, sim_research_q, sim_industry, sim_international]

        fig_radar = go.Figure()
        fig_radar.add_trace(go.Scatterpolar(
            r=current_vals, theta=categories, fill='toself',
            name='Current', line_color='#6366f1', opacity=0.6))
        fig_radar.add_trace(go.Scatterpolar(
            r=simulated_vals, theta=categories, fill='toself',
            name='Simulated', line_color='#10b981', opacity=0.6))
        fig_radar.update_layout(
            polar=dict(radialaxis=dict(visible=True, range=[0,100])),
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            margin=dict(l=40, r=40, t=20, b=20)
        )
        st.plotly_chart(fig_radar, use_container_width=True)

    # SECTION 3: Estimated Rank Calculation (Official WUR 3.0 Weights)
    composite_score = (
        sim_teaching * 0.295 +
        sim_research_env * 0.290 +
        sim_research_q * 0.300 +
        sim_industry * 0.040 +
        sim_international * 0.075
    )

    if composite_score >= 70: estimated_rank = "Top 200"
    elif composite_score >= 60: estimated_rank = "201-400"
    elif composite_score >= 50: estimated_rank = "401-600"
    elif composite_score >= 40: estimated_rank = "601-800"
    elif composite_score >= 30: estimated_rank = "801-1000"
    elif composite_score >= 22: estimated_rank = "1001-1250"
    elif composite_score >= 18: estimated_rank = "1251-1500"
    else: estimated_rank = "1501+"

    # Color logic
    if estimated_rank != "1501+":
        rank_color = "#10b981" # Green
    else:
        rank_color = "#f59e0b" if total_delta > 0 else "#ef4444" # Orange or Red
        
    st.markdown("### Simulated Results")
    res_cols = st.columns(3)
    with res_cols[0]:
        st.markdown(create_kpi_card("Current Rank", "1501+"), unsafe_allow_html=True)
    with res_cols[1]:
        st.markdown(f'''
        <div class="kpi-card" style="border: 2px solid {rank_color};">
            <div class="kpi-title">Simulated Rank</div>
            <div class="kpi-value" style="color: {rank_color};">{estimated_rank}</div>
        </div>
        ''', unsafe_allow_html=True)
    with res_cols[2]:
        st.markdown(create_kpi_card("Composite Score", f"{composite_score:.1f} / 100"), unsafe_allow_html=True)

    st.markdown(f"**Total Improvement:** <span style='color:#10b981;'>+{total_delta:.1f} points</span>", unsafe_allow_html=True)
    
    # SECTION 4: Required Actions per Criterion
    if total_delta > 0:
        st.markdown("#### Required Interventions")
        if d_teaching > 0:
            st.info(f"**Teaching (+{d_teaching:.1f} pts) :** Hire additional professors, reduce student/staff ratio.")
        if d_research_env > 0:
            st.info(f"**Research Environment (+{d_research_env:.1f} pts) :** Invest in lab infrastructure, recruit senior researchers.")
        if d_research_q > 0:
            st.info(f"**Research Quality (+{d_research_q:.1f} pts) :** Publish more papers in Q1 journals, secure international research grants.")
        if d_industry > 0:
            st.info(f"**Industry (+{d_industry:.1f} pts) :** Sign new industry partnerships, launch commercial internship programs.")
        if d_international > 0:
            st.info(f"**International Outlook (+{d_international:.1f} pts) :** Increase Erasmus agreements, recruit international students.")

    # SECTION 5: AI Strategic Analysis Button
    st.markdown("---")
    st.markdown("#### AI Roadmap Generator")
    if st.button("Generate AI Roadmap for this simulation", key="btn_sim_roadmap"):
        prompt = (
            f"Based on these target THE scores: Teaching: {sim_teaching:.1f}, Research Env: {sim_research_env:.1f}, "
            f"Research Quality: {sim_research_q:.1f}, Industry: {sim_industry:.1f}, International: {sim_international:.1f}. "
            f"The University of Carthage wants to go from rank 1501+ to {estimated_rank}. "
            f"Generate a precise 12-month action plan in French with: "
            f"1. Top 3 priority actions with deadlines "
            f"2. Required budget investment estimate in TND "
            f"3. Which institutions in the UCAR network should lead each action "
            f"4. Expected rank improvement timeline (quarterly). "
            f"Be specific, quantitative, and executive-level."
        )
        
        with st.spinner("Generating AI Roadmap via Grok..."):
            response = ask_grok(prompt)
            st.markdown("###  Grok AI Action Plan")
            st.markdown(f'''
            <div style="background:#1E1E2E; padding:20px; border-radius:8px; border:1px solid rgba(16,185,129,0.3);">
                {response}
            </div>
            ''', unsafe_allow_html=True)

    st.markdown("---")
    st.markdown("### UCAR vs THE Benchmark Comparison")
    
    # STEP 1: THE Averages (Live from THE website - 2000+ universities)
    with st.spinner("Fetching real THE global averages from 2000+ universities..."):
        the_averages = fetch_the_global_averages()
    
    if the_averages:
        the_avg_teaching = the_averages['teaching']
        the_avg_research_env = the_averages['research_env']
        the_avg_research_quality = the_averages['research_quality']
        the_avg_industry = the_averages['industry']
        the_avg_international = the_averages['international']
        global_total = the_averages['valid']
        st.success(f"Moyennes calcul\u00e9es en direct depuis {the_averages['total']} universit\u00e9s ({global_total} avec scores valides)")
    else:
        st.warning("Impossible de r\u00e9cup\u00e9rer les donn\u00e9es THE en direct. V\u00e9rifiez votre connexion.")
        the_avg_teaching = the_avg_research_env = the_avg_research_quality = the_avg_industry = the_avg_international = 0
        global_total = 0

    # STEP 2: UCAR Internal KPIs (Using Dynamic Baseline)
    ucar_teaching = base_teaching
    ucar_research_env = base_research_env
    ucar_research = base_research_q
    ucar_industry = base_industry
    ucar_international = base_international
    
    # STEP 3: Comparison Table
    comp_data = {
        "Criterion": ["Teaching", "Research Env", "Research Quality", "Industry", "International"],
        "THE Global Average": [the_avg_teaching, the_avg_research_env, the_avg_research_quality, the_avg_industry, the_avg_international],
        "UCAR Internal": [ucar_teaching, ucar_research_env, ucar_research, ucar_industry, ucar_international]
    }
    comp_df = pd.DataFrame(comp_data)
    comp_df["Gap"] = comp_df["UCAR Internal"] - comp_df["THE Global Average"]
    
    def get_status(gap):
        if gap >= 0: return " Above"
        elif gap >= -5: return " Close"
        else: return " Below"
        
    comp_df["Status"] = comp_df["Gap"].apply(get_status)
    
    st.dataframe(comp_df.style.format({
        "THE Global Average": "{:.1f}", 
        "UCAR Internal": "{:.1f}", 
        "Gap": "{:.1f}"
    }), use_container_width=True)
    
    # STEP 4: Bar Chart
    import plotly.express as px
    
    # Melt for plotly express grouped bar chart
    bar_df = pd.melt(comp_df, id_vars=['Criterion'], value_vars=['THE Global Average', 'UCAR Internal'],
                     var_name='Metric Type', value_name='Score')
                     
    fig_comp = px.bar(bar_df, x='Criterion', y='Score', color='Metric Type', barmode='group',
                      title="UCAR vs THE Global Benchmark (2191 Universities)",
                      color_discrete_map={"THE Global Average": "#6366f1", "UCAR Internal": "#10b981"})
    
    # Add horizontal lines
    for i, row in comp_df.iterrows():
        fig_comp.add_shape(type="line", x0=i-0.4, x1=i+0.4, y0=row["THE Global Average"], y1=row["THE Global Average"],
                           line=dict(color="red", width=2, dash="dash"))
                           
    fig_comp.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
    st.plotly_chart(fig_comp, use_container_width=True)
    

            
    # STEP 6: Overall Match Score
    gaps = [
        abs(ucar_teaching - the_avg_teaching),
        abs(ucar_research - the_avg_research_quality),
        abs(ucar_research_env - the_avg_research_env),
        abs(ucar_industry - the_avg_industry),
        abs(ucar_international - the_avg_international)
    ]
    
    alignment_score = 100 - (sum(gaps) / len(gaps))
    alignment_score = max(0, min(100, alignment_score))
    
    if alignment_score >= 70: align_color = "#10b981"
    elif alignment_score >= 50: align_color = "#f59e0b"
    else: align_color = "#ef4444"
    
    st.markdown("---")
    st.markdown(f'''
    <div class="kpi-card" style="border: 2px solid {align_color}; text-align: center;">
        <div class="kpi-title" style="font-size: 16px;">Benchmark Alignment Score</div>
        <div class="kpi-value" style="color: {align_color}; font-size: 32px;">{alignment_score:.1f}/100</div>
    </div>
    ''', unsafe_allow_html=True)
