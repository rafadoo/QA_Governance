import streamlit as st
import pandas as pd
import os
import plotly.express as px
from datetime import datetime
from fpdf import FPDF
from fpdf.enums import XPos, YPos
import tempfile
from supabase import create_client, Client
import requests

# --- CONFIGURAÇÃO SUPABASE ---
# As chaves devem ser configuradas no Streamlit Cloud (Settings > Secrets)
try:
    SUPABASE_URL = st.secrets["SUPABASE_URL"]
    SUPABASE_KEY = st.secrets["SUPABASE_KEY"]
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
except Exception:
    st.error("Configure as chaves SUPABASE_URL e SUPABASE_KEY nos Secrets do Streamlit.")
    st.stop()

# --- CONFIGURAÇÃO VISUAL ---
st.set_page_config(page_title="QA Governance ", layout="wide")

STATUS_OPCOES = ["Pendente", "Em Execucao", "OK", "Falha", "Bloqueado", "N/A"]
PRIORIDADE_OPCOES = ["Baixa", "Media", "Alta", "Critica"]

CORES_GRAF = {
    "OK": "#4b4c6a",        
    "Falha": "#780096",       
    "Pendente": "#c2c7cd",
    "Bloqueado": "#5f365e",
    "Em Execucao": "#848dae"
}

# --- FUNÇÕES DE APOIO ---
def get_next_auto_id(prefix, table, col, exec_id):
    res = supabase.table(table).select(col).eq("exec_id", exec_id).order("id", desc=True).limit(1).execute()
    if not res.data: return f"{prefix}-001"
    try:
        num = int(res.data[0][col].split('-')[1])
        return f"{prefix}-{str(num + 1).zfill(3)}"
    except: return f"{prefix}-001"

# --- PDF REPORT ENGINE ---
class QAReport(FPDF):
    def header(self):
        self.set_font('helvetica', 'B', 10)
        self.set_text_color(100, 100, 100)
        self.cell(0, 10, 'SISTEMA DE GOVERNANCA DE QA - RELATORIO SUPABASE', new_x=XPos.LMARGIN, new_y=YPos.NEXT, align='L')
        self.line(15, 18, 195, 18)
        self.ln(5)

    def section_header(self, title):
        self.ln(5)
        self.set_font('helvetica', 'B', 12)
        self.set_fill_color(245, 247, 249)
        self.set_text_color(44, 62, 80)
        self.cell(0, 10, f" {title.upper()}", fill=True, new_x=XPos.LMARGIN, new_y=YPos.NEXT, align='L')
        self.ln(3)

def gerar_pdf_completo(ciclo_nome, df_testes, df_crits, exec_id, img_pie_path, img_bar_path):
    pdf = QAReport()
    pdf.set_margins(15, 15, 15)
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.add_page()
    
    # Capa
    pdf.set_y(60)
    pdf.set_font('helvetica', 'B', 26)
    pdf.cell(0, 20, "RELATORIO DE EXECUCAO", new_x=XPos.LMARGIN, new_y=YPos.NEXT, align='C')
    pdf.set_font('helvetica', 'B', 18)
    pdf.set_text_color(127, 140, 141)
    pdf.cell(0, 10, ciclo_nome.upper(), new_x=XPos.LMARGIN, new_y=YPos.NEXT, align='C')
    
    # Gráficos
    if img_pie_path and img_bar_path:
        pdf.add_page()
        pdf.section_header("ANALISES DE PERFORMANCE")
        pdf.image(img_pie_path, x=55, y=pdf.get_y() + 5, w=100)
        pdf.set_y(pdf.get_y() + 105)
        pdf.image(img_bar_path, x=25, y=pdf.get_y() + 5, w=160)

    # Critérios e Testes (Logica de download de evidências via URL)
    pdf.add_page()
    pdf.section_header("DETALHAMENTO")
    
    # Buscar evidências do Supabase
    evs_data = supabase.table("evidencias").select("caminho, test_id").eq("exec_id", exec_id).execute().data
    
    for _, r in df_testes.iterrows():
        pdf.set_font('helvetica', 'B', 10)
        pdf.cell(0, 8, f" {r['ID']} | {r['Titulo']}", fill=True, border='B', new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        
        # Download temporário para o PDF
        current_evs = [e['caminho'] for e in evs_data if e['test_id'] == r['ID']]
        for url in current_evs:
            try:
                img_content = requests.get(url).content
                with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tmp:
                    tmp.write(img_content)
                    pdf.image(tmp.name, w=90)
                os.unlink(tmp.name)
            except: pass
            
    return bytes(pdf.output())

# --- LOGIN ---
if 'user' not in st.session_state: st.session_state['user'] = None

if st.session_state['user'] is None:
    st.title("Login - QA Governance")
    with st.container(border=True):
        em = st.text_input("E-mail corporativo")
        pw = st.text_input("Senha", type="password")
        if st.button("Acessar", use_container_width=True):
            u = supabase.table("usuarios").select("*").eq("email", em).eq("senha", pw).execute()
            if u.data:
                st.session_state['user'] = u.data[0]
                st.rerun()
            else: st.error("Acesso negado.")
    st.stop()

# --- APP ---
user = st.session_state['user']
with st.sidebar:
    st.subheader(f"👤 {user['nome']}")
    if st.button("Sair"): st.session_state['user'] = None; st.rerun()
    
    with st.form("new_ciclo"):
        t = st.text_input("Título do Novo Ciclo")
        if st.form_submit_button("Criar Ciclo", use_container_width=True):
            supabase.table("execucoes").insert({"user_id": user['id'], "titulo": t, "data": datetime.now().strftime("%Y-%m-%d")}).execute()
            st.rerun()
    
    q_execs = supabase.table("execucoes").select("*")
    if not user['pode_ver_todos']: q_execs = q_execs.eq("user_id", user['id'])
    execs_data = q_execs.execute().data
    df_execs = pd.DataFrame(execs_data)
    ciclo_ativo = st.selectbox("Ciclo Ativo", df_execs['titulo'].tolist() if not df_execs.empty else ["Nenhum"])

if ciclo_ativo != "Nenhum":
    exec_id = int(df_execs[df_execs['titulo'] == ciclo_ativo]['id'].values[0])
    
    # Buscar Dados (Sincronizando campos revisados)
    crits_data = supabase.table("criterios").select("crit_id, funcionalidade, descricao, tipo, prioridade, responsavel, status").eq("exec_id", exec_id).execute().data
    df_c = pd.DataFrame(crits_data) if crits_data else pd.DataFrame(columns=['ID','Funcionalidade','Descricao','Tipo','Prioridade','Responsavel','Status'])
    if crits_data: df_c.columns = ['ID','Funcionalidade','Descricao','Tipo','Prioridade','Responsavel','Status']

    tests_data = supabase.table("casos_teste").select("test_id, funcionalidade, titulo, passos, esperado, status, observacao").eq("exec_id", exec_id).execute().data
    df_t = pd.DataFrame(tests_data) if tests_data else pd.DataFrame(columns=['ID','Funcionalidade','Titulo','Passos','Esperado','Status','Observacao'])
    if tests_data: df_t.columns = ['ID','Funcionalidade','Titulo','Passos','Esperado','Status','Observacao']

    tabs = st.tabs(["Dashboard", "Critérios", "Execução", "Exportar"])

    with tabs[0]:
        if not df_t.empty:
            c1, c2 = st.columns(2)
            fig_pie = px.pie(df_t, names='Status', title="Status Geral", color='Status', color_discrete_map=CORES_GRAF, hole=0.5)
            c1.plotly_chart(fig_pie, use_container_width=True)
            fig_bar = px.bar(df_t, x='Funcionalidade', color='Status', title="Módulos", color_discrete_map=CORES_GRAF)
            c2.plotly_chart(fig_bar, use_container_width=True)

    with tabs[1]:
        if st.button("➕ Novo Critério"):
            nid = get_next_auto_id("CA", "criterios", "crit_id", exec_id)
            supabase.table("criterios").insert({"exec_id": exec_id, "crit_id": nid, "status": "Pendente"}).execute()
            st.rerun()
        
        ed_c = st.data_editor(df_c, key="ed_c", num_rows="dynamic", use_container_width=True,
                             column_config={"Status": st.column_config.SelectboxColumn("Status", options=STATUS_OPCOES),
                                           "Prioridade": st.column_config.SelectboxColumn("Prioridade", options=PRIORIDADE_OPCOES)})
        
        if st.button("Salvar Critérios", use_container_width=True):
            supabase.table("criterios").delete().eq("exec_id", exec_id).execute()
            for _, r in ed_c.iterrows():
                supabase.table("criterios").insert({
                    "exec_id": exec_id, "crit_id": r['ID'], "funcionalidade": r.get('Funcionalidade',''),
                    "descricao": r.get('Descricao',''), "tipo": r.get('Tipo',''), 
                    "prioridade": r.get('Prioridade',''), "responsavel": r.get('Responsavel',''), "status": r.get('Status','Pendente')
                }).execute()
            st.success("Sincronizado no Supabase!")

    with tabs[2]:
        if st.button("➕ Novo Caso de Teste"):
            nid = get_next_auto_id("CT", "casos_teste", "test_id", exec_id)
            supabase.table("casos_teste").insert({"exec_id": exec_id, "test_id": nid, "status": "Pendente"}).execute()
            st.rerun()
        
        ed_t = st.data_editor(df_t, key="ed_t", num_rows="dynamic", use_container_width=True,
                             column_config={"Status": st.column_config.SelectboxColumn("Status", options=STATUS_OPCOES)})
        
        if st.button("Salvar Execução", use_container_width=True):
            supabase.table("casos_teste").delete().eq("exec_id", exec_id).execute()
            for _, r in ed_t.iterrows():
                supabase.table("casos_teste").insert({
                    "exec_id": exec_id, "test_id": r['ID'], "funcionalidade": r.get('Funcionalidade',''),
                    "titulo": r.get('Titulo',''), "passos": r.get('Passos',''), 
                    "esperado": r.get('Esperado',''), "status": r.get('Status','Pendente'), "observacao": r.get('Observacao','')
                }).execute()
            st.success("Sincronizado!")

    with tabs[3]:
        st.subheader("Anexos na Nuvem")
        target = st.selectbox("ID do Teste", df_t['ID'].tolist() if not df_t.empty else [])
        img = st.file_uploader("Upload de Evidência", type=['png','jpg','jpeg'])
        if st.button("Vincular ao Supabase") and img:
            file_path = f"{exec_id}/{target}_{img.name}"
            supabase.storage.from_("evidencias").upload(file_path, img.getvalue(), {"upsert": "true"})
            url = supabase.storage.from_("evidencias").get_public_url(file_path)
            supabase.table("evidencias").insert({"exec_id": exec_id, "test_id": target, "caminho": url, "data": datetime.now().strftime("%Y-%m-%d")}).execute()
            st.success("Evidência salva no Storage!")

        if st.button("Gerar Relatório PDF", use_container_width=True):
            with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as t1, tempfile.NamedTemporaryFile(delete=False, suffix=".png") as t2:
                for f in [fig_pie, fig_bar]: f.update_layout(paper_bgcolor='white', plot_bgcolor='white')
                fig_pie.write_image(t1.name, engine="kaleido", scale=2)
                fig_bar.write_image(t2.name, engine="kaleido", scale=2)
                pdf_data = gerar_pdf_completo(ciclo_ativo, df_t, df_c, exec_id, t1.name, t2.name)
                st.session_state['pdf_final'] = pdf_data
                st.success("PDF gerado!")

        if 'pdf_final' in st.session_state:
            st.download_button("Baixar PDF", st.session_state['pdf_final'], f"QA_{ciclo_ativo}.pdf", use_container_width=True)
