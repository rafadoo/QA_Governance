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
        self.cell(0, 10, 'SISTEMA DE GOVERNANCA DE QA - RELATORIO DE EXECUÇÃO', new_x=XPos.LMARGIN, new_y=YPos.NEXT, align='L')
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
    
    # --- PÁGINA 1: CAPA ---
    pdf.add_page()
    pdf.set_y(80)
    pdf.set_font('helvetica', 'B', 28)
    pdf.set_text_color(44, 62, 80)
    pdf.cell(0, 20, "RELATÓRIO DE EXECUÇÃO DE QA", new_x=XPos.LMARGIN, new_y=YPos.NEXT, align='C')
    
    pdf.set_font('helvetica', 'B', 16)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(0, 10, f"PROJETO: {ciclo_nome.upper()}", new_x=XPos.LMARGIN, new_y=YPos.NEXT, align='C')
    
    pdf.set_y(250)
    pdf.set_font('helvetica', 'I', 10)
    pdf.cell(0, 10, f"Gerado em: {datetime.now().strftime('%d/%m/%Y %H:%M')}", align='C')

    # --- PÁGINA 2: DASHBOARD & RESUMO ---
    pdf.add_page()
    pdf.section_header("SUMÁRIO EXECUTIVO")
    
    # Tabela de Resumo de Status
    status_counts = df_testes['Status'].value_counts()
    pdf.set_font('helvetica', 'B', 10)
    pdf.set_fill_color(230, 230, 230)
    pdf.cell(90, 8, "Status", border=1, fill=True)
    pdf.cell(90, 8, "Quantidade", border=1, fill=True, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    
    pdf.set_font('helvetica', '', 10)
    for status, count in status_counts.items():
        pdf.cell(90, 8, f" {status}", border=1)
        pdf.cell(90, 8, f" {count}", border=1, new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    # Gráficos
    if img_pie_path and img_bar_path:
        pdf.ln(10)
        pdf.image(img_pie_path, x=55, w=100)
        pdf.ln(5)
        pdf.image(img_bar_path, x=20, w=170)

    # --- PÁGINA 3: CRITÉRIOS DE ACEITE ---
    if not df_crits.empty:
        pdf.add_page()
        pdf.section_header("CRITÉRIOS DE ACEITE")
        pdf.set_font('helvetica', 'B', 9)
        pdf.set_fill_color(200, 205, 210)
        pdf.cell(25, 8, "ID", border=1, fill=True)
        pdf.cell(100, 8, "Descrição", border=1, fill=True)
        pdf.cell(30, 8, "Prioridade", border=1, fill=True)
        pdf.cell(25, 8, "Status", border=1, fill=True, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        
        pdf.set_font('helvetica', '', 8)
        for _, c in df_crits.iterrows():
            pdf.cell(25, 7, f" {c['ID']}", border=1)
            pdf.cell(100, 7, f" {str(c['Descricao'])[:60]}...", border=1)
            pdf.cell(30, 7, f" {c['Prioridade']}", border=1)
            pdf.cell(25, 7, f" {c['Status']}", border=1, new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    # --- DETALHAMENTO DOS TESTES ---
    pdf.add_page()
    pdf.section_header("DETALHAMENTO DA EXECUÇÃO")

    largura_util = pdf.w - pdf.l_margin - pdf.r_margin
    
    evs_data = supabase.table("evidencias").select("caminho, test_id").eq("exec_id", exec_id).execute().data
    
    for _, r in df_testes.iterrows():
        # Verificação de quebra de página preventiva (se restar menos de 60mm)
        if pdf.get_y() > 230: 
            pdf.add_page()
            
        # 1. Cabeçalho do Bloco de Teste
        pdf.set_font('helvetica', 'B', 11)
        pdf.set_fill_color(44, 62, 80)
        pdf.set_text_color(255, 255, 255)
        pdf.cell(largura_util, 10, f" {r['ID']} | {r['Titulo']}", fill=True, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        
        # 2. Linha de Status e Módulo (Com Cores)
        pdf.set_text_color(0, 0, 0)
        pdf.set_font('helvetica', 'B', 9)
        pdf.cell( largura_util * 0.5, 8, f" MÓDULO: {r['Funcionalidade']}", border='B')
        
        # Define a cor do texto do Status
        status_color = (75, 76, 106) # Cor padrão (Pendente)
        if r['Status'] == "OK": status_color = (30, 130, 76) # Verde
        elif r['Status'] == "Falha": status_color = (120, 0, 150) # Roxo
        
        pdf.set_text_color(*status_color)
        pdf.cell(largura_util * 0.5, 8, f" STATUS: {r['Status']}", border='B', new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        
        # 3. Passos (Reseta cursor para a margem esquerda)
        pdf.set_text_color(0, 0, 0)
        pdf.ln(2)
        pdf.set_font('helvetica', 'B', 9)
        pdf.set_x(pdf.l_margin)
        pdf.cell(largura_util, 7, "Passos:", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        
        pdf.set_font('helvetica', '', 9)
        texto_passos = str(r['Passos']) if r['Passos'] and str(r['Passos']) != 'None' else "N/A"
        pdf.multi_cell(largura_util, 5, texto_passos, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        
        # 4. Resultado Esperado
        pdf.ln(1)
        pdf.set_font('helvetica', 'B', 9)
        pdf.set_x(pdf.l_margin)
        pdf.cell(largura_util, 7, "Resultado Esperado:", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        
        pdf.set_font('helvetica', '', 9)
        texto_esperado = str(r['Esperado']) if r['Esperado'] and str(r['Esperado']) != 'None' else "N/A"
        pdf.multi_cell(largura_util, 5, texto_esperado, new_x=XPos.LMARGIN, new_y=YPos.NEXT)

        # 5. Observações (Se existirem)
        if r['Observacao'] and str(r['Observacao']) != 'None':
            pdf.ln(2)
            pdf.set_font('helvetica', 'I', 9)
            pdf.set_text_color(150, 0, 0) # Texto em tom avermelhado para avisos
            pdf.set_x(pdf.l_margin)
            pdf.multi_cell(largura_util, 5, f"Obs: {r['Observacao']}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            pdf.set_text_color(0, 0, 0)

        # 6. Evidências (Imagens do Supabase Storage)
        current_evs = [e['caminho'] for e in evs_data if e['test_id'] == r['ID']]
        if current_evs:
            pdf.ln(3)
            for url in current_evs:
                try:
                    img_content = requests.get(url, timeout=10).content
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tmp:
                        tmp.write(img_content)
                        tmp_path = tmp.name
                    
                    # Centralização lógica da imagem (Página tem 210mm, margens 15mm cada)
                    # Imagem com 140mm de largura
                    pdf.image(tmp_path, x=35, w=140) 
                    pdf.ln(2)
                    os.unlink(tmp_path)
                except:
                    pdf.set_font('helvetica', 'I', 8)
                    pdf.cell(largura_util, 5, " [Evidência anexada, mas não pôde ser carregada no PDF] ", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        
        pdf.ln(10) # Espaçamento final entre blocos de teste
            
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

    bugs_data = supabase.table("bugs").select("*").eq("exec_id", exec_id).execute().data
    df_bugs = pd.DataFrame(bugs_data) if bugs_data else pd.DataFrame(columns=['id', 'titulo', 'descricao', 'aplicacao', 'ambiente', 'prioridade', 'funcionalidade', 'status', 'id_externo', 'status_integracao'])

    tabs = st.tabs(["Dashboard", "Critérios", "Execução", "Exportar", "Bugs"])

    with tabs[0]:
        st.subheader(f"QA Governance - {ciclo_ativo}")
        if not df_t.empty:
            c1, c2 = st.columns(2)
            fig_pie = px.pie(df_t, names='Status', title="Status Geral", color='Status', color_discrete_map=CORES_GRAF, hole=0.5)
            c1.plotly_chart(fig_pie, use_container_width=True)
            fig_bar = px.bar(df_t, x='Funcionalidade', color='Status', title="Módulos", color_discrete_map=CORES_GRAF)
            c2.plotly_chart(fig_bar, use_container_width=True)

    if not df_bugs.empty:
        st.divider()
        st.subheader("Indicadores de Defeitos")
        c1, c2 = st.columns(2)
        
        fig_bugs_prio = px.pie(df_bugs, names='prioridade', title="Bugs por Prioridade", hole=0.4)
        c1.plotly_chart(fig_bugs_prio, use_container_width=True)
        
        fig_bugs_status = px.bar(df_bugs, x='status', color='status_integracao', title="Status de Correção vs Integração")
        c2.plotly_chart(fig_bugs_status, use_container_width=True)            

    with tabs[1]:
        st.subheader(f"Critérios de Aceite - {ciclo_ativo}")
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
            st.success("Sincronizado!")

    with tabs[2]:
        st.subheader(f"Casos de Teste - {ciclo_ativo}")
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
        if st.button("Vincular ao Caso de Teste") and img:
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

    with tabs[4]: # Aba de Bugs
        st.subheader(f"Gestão de Bugs - {ciclo_ativo}")
        
        # Busca Bugs vinculados a esta execução
        bugs_data = supabase.table("bugs").select("*").eq("exec_id", exec_id).execute().data
        df_bugs = pd.DataFrame(bugs_data) if bugs_data else pd.DataFrame(columns=[
            'id', 'titulo', 'descricao', 'aplicacao', 'ambiente', 'prioridade', 
            'funcionalidade', 'status', 'id_externo', 'status_integracao'
        ])  

        # --- Formulário de Cadastro ---
        with st.expander("➕ Reportar Novo Bug"):
            with st.form("form_bug"):
                col1, col2 = st.columns(2)
                b_titulo = col1.text_input("Título do Bug")
                b_func = col2.selectbox("Funcionalidade (Módulo)", df_t['Funcionalidade'].unique() if not df_t.empty else ["Geral"])
                b_desc = st.text_area("Descrição Detalhada / Passos para Reproduzir")
                
                c3, c4, c5 = st.columns(3)
                b_app = c3.text_input("Aplicação", placeholder="Ex: App Android, Site...")
                b_amb = c4.selectbox("Ambiente", ["Desenvolvimento", "Homologação", "Produção"])
                b_prio = c5.selectbox("Prioridade", PRIORIDADE_OPCOES)
                
                if st.form_submit_button("Registrar Bug", use_container_width=True):
                    new_bug = {
                        "exec_id": exec_id,
                        "titulo": b_titulo,
                        "funcionalidade": b_func,
                        "descricao": b_desc,
                        "aplicacao": b_app,
                        "ambiente": b_amb,
                        "prioridade": b_prio,
                        "status": "Novo"
                    }
                    supabase.table("bugs").insert(new_bug).execute()
                    st.success("Bug registrado com sucesso!")
                    st.rerun()  

        # --- Edição e Visualização ---
        if not df_bugs.empty:
            st.write("### Lista de Defeitos")
            
            # Configuração do Data Editor para lidar com a lógica de Integração
            ed_bugs = st.data_editor(
                df_bugs, 
                key="editor_bugs",
                use_container_width=True,
                column_config={
                    "id": None, # Oculta o ID interno
                    "exec_id": None,
                    "status": st.column_config.SelectboxColumn("Status", options=["Novo", "Em Correção", "Validado", "Cancelado"]),
                    "prioridade": st.column_config.SelectboxColumn("Prioridade", options=PRIORIDADE_OPCOES),
                    "status_integracao": st.column_config.TextColumn("Status Integração", disabled=True),
                    "id_externo": st.column_config.TextColumn("ID Externo (Jira/Azure)")
                },
                hide_index=True
            )   

            if st.button("Salvar Alterações nos Bugs", use_container_width=True):
                for _, row in ed_bugs.iterrows():
                    # Lógica de Integração Automática solicitada
                    status_int = "Integrado" if row['id_externo'] and str(row['id_externo']).strip() != "" else "Nao Integrado"
                    
                    upd_data = {
                        "titulo": row['titulo'],
                        "descricao": row['descricao'],
                        "aplicacao": row['aplicacao'],
                        "ambiente": row['ambiente'],
                        "prioridade": row['prioridade'],
                        "status": row['status'],
                        "id_externo": row['id_externo'],
                        "status_integracao": status_int
                    }
                    supabase.table("bugs").update(upd_data).eq("id", row['id']).execute()
                
                st.success("Bugs atualizados!")
                st.rerun()
        else:
            st.info("Nenhum bug reportado para este ciclo.")