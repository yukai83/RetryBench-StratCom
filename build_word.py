"""Build an editable two-column Word working copy from the canonical IEEE TeX."""
from pathlib import Path
import re,subprocess
from docx import Document
from docx.shared import Inches,Pt,RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
ROOT=Path(__file__).parent
source=(ROOT/'main.tex').read_text()
# Inline \input files and resolve \ref from LaTeX's own aux numbering (run pdflatex first).
source=source.replace(r'\input{tables/heldout_all.tex}',r'\input{tables/heldout_all_word.tex}')
source=re.sub(r'\\input\{([^}]+)\}',lambda m:(ROOT/(m.group(1) if m.group(1).endswith('.tex') else m.group(1)+'.tex')).read_text(),source)
labels={k:re.sub(r'\\mbox\s*\{([^}]*)\}',r'\1',v).replace('{','').replace('}','').strip()
        for k,v in re.findall(r'\\newlabel\{([^}]+)\}\{\{((?:[^{}]|\{[^{}]*\})*)\}',(ROOT/'main.aux').read_text())}
source=re.sub(r'\\ref\{([^}]+)\}',lambda m:labels.get(m.group(1),'??'),source)
source=source.replace('figure*','figure').replace('table*','table')
source=re.sub(r'\\cmidrule(\([a-z]+\))?\{[^}]*\}','',source)
# pandoc does not resolve manual LaTeX thebibliography references; emit explicit
# numbered citation text for the editable document, without touching master PDF.
refs={x:i+1 for i,x in enumerate(re.findall(r'\\bibitem\{([^}]+)\}',source))}
source=re.sub(r'\\cite\{([^}]+)\}',lambda m:'['+'], ['.join(str(refs[x.strip()]) for x in m.group(1).split(','))+']',source)
source=source.replace(r'\tau$-bench',r'\tau$-bench')
source=source.replace(r"\beta_{\rm short}",r"\beta_{\mathrm{short}}").replace(r"\beta_{\rm long}",r"\beta_{\mathrm{long}}")
source=source.replace(r'\texttt{sdk\_style\_proxy}',r'\texttt{sdk\_style\_proxy}')
# convert the bibliography into individual blocks on the Word side.
start=source.index(r'\balance')
pre=source[:start]+r'\end{document}'
(ROOT/'_word_sanitized.tex').write_text(pre)
subprocess.run(['pandoc',str(ROOT/'_word_sanitized.tex'),'-f','latex','-t','docx','--resource-path='+str(ROOT)+':'+str(ROOT/'figures'),'-o',str(ROOT/'_word_raw.docx')],check=True,cwd=ROOT,capture_output=True,text=True)
doc=Document(ROOT/'_word_raw.docx')
sec=doc.sections[0];sec.page_height=Inches(11.69);sec.page_width=Inches(8.27)
sec.top_margin=Inches(.77);sec.bottom_margin=Inches(.73)
sec.left_margin=Inches(.7);sec.right_margin=Inches(.7)
sec.header_distance=Inches(.3);sec.footer_distance=Inches(.3)
# Use consistent two columns from page one. LibreOffice adds a full blank
# first page when switching columns after the abstract, so the Word working copy
# prioritizes readable/editable pagination over an identical IEEE title block.
cols=sec._sectPr.xpath('./w:cols')
if cols:
 cols[0].set(qn('w:num'),'2');cols[0].set(qn('w:space'),'340')
else:
 c=OxmlElement('w:cols');c.set(qn('w:num'),'2');c.set(qn('w:space'),'340');sec._sectPr.append(c)
# normalize formatting and paragraph cadence. Figure/heading layout is checked by render.
styles=doc.styles
for sty in ('Normal','Body Text','First Paragraph'):
 if sty in styles:
  st=styles[sty];st.font.name='Times New Roman';st.font.size=Pt(8.5)
  st.paragraph_format.space_after=Pt(2)
  st.paragraph_format.line_spacing=1.0
for sty in ['Heading 1','Heading 2']:
 try:
  st=styles[sty];st.font.name='Times New Roman';st.font.size=Pt(9 if sty=='Heading 1' else 8.5)
  st.font.color.rgb=RGBColor(0,0,0)
  st.paragraph_format.space_before=Pt(5);st.paragraph_format.space_after=Pt(2)
 except KeyError: pass
for i,p in enumerate(doc.paragraphs):
 if i==0:
  p.alignment=WD_ALIGN_PARAGRAPH.CENTER
  for r in p.runs:r.font.name='Times New Roman';r.font.size=Pt(13);r.font.color.rgb=RGBColor(0,0,0)
 elif i in (1,2,3):
  p.alignment=WD_ALIGN_PARAGRAPH.JUSTIFY
  for r in p.runs:r.font.name='Times New Roman';r.font.size=Pt(8.5)
 elif p.style.name in ('Heading 1','Heading 2','Abstract Title'):
  for r in p.runs:
   r.font.name='Times New Roman';r.font.color.rgb=RGBColor(0,0,0)
   r.font.size=Pt(9 if p.style.name=='Heading 1' else 8.5)
 elif p.style.name.startswith('Caption') or p.style.name=='Captioned Figure':
  p.alignment=WD_ALIGN_PARAGRAPH.CENTER
  for r in p.runs:r.font.size=Pt(7.5)
 elif p.style.name in ('Body Text','First Paragraph','Normal'):
  p.alignment=WD_ALIGN_PARAGRAPH.JUSTIFY
 # fix a Pandoc source underreport due to unsupported tau symbol in raw paragraphs
 if '-bench' in p.text and 'tool-agent' not in p.text:
  for r in p.runs:r.text=r.text.replace('-bench','τ-bench')
# Word title affiliation sourced from LaTex author block; pandoc often omits it.
title=doc.paragraphs[0]
author=title.insert_paragraph_before('Yukai Zeng | Singapore Ministry of Defence Communications Organisation (MCO)')
author.alignment=WD_ALIGN_PARAGRAPH.CENTER
for run in author.runs:run.font.name='Times New Roman';run.font.size=Pt(8)
# Author was inserted before title: reposition just after title.
title._p.addnext(author._p)
# Re-identify keywords paragraph for section break unaffected by moving nodes.
# Add explicit separate reference entries at end. The canonical TeX remains authoritative.
doc.add_paragraph('REFERENCES')
for key,index in refs.items():
 item=re.search(r'\\bibitem\{'+re.escape(key)+r'\}\s*(.*?)(?=\n\\bibitem\{|\n\\end\{thebibliography\})',source,flags=re.S)
 if not item:continue
 txt=item.group(1).replace('\n',' ').strip()
 txt=re.sub(r'\\emph\{([^}]+)\}',r'\1',txt)
 txt=re.sub(r'\\mbox\{([^}]+)\}',r'\1',txt)
 txt=re.sub(r'\\url\{([^}]+)\}',r'\1',txt)
 txt=re.sub(r'\\tau',r'τ',txt)
 txt=txt.replace(r'\emph','').replace(r'\v{z}','ž').replace(r'\=a','ā')
 txt=txt.replace('\\','').replace('{','').replace('}','')
 txt=txt.replace('$τ$-bench','τ-bench').replace('St$-bench','τ-bench').replace('$τ$','τ')
 txt=txt.replace('``','“').replace("''",'”').replace('---','—')
 para=doc.add_paragraph(f'[{index}] {txt}')
 para.style='Normal';para.paragraph_format.left_indent=Inches(.16);para.paragraph_format.first_line_indent=Inches(-.16)
 para.paragraph_format.space_after=Pt(1)
 for run in para.runs:run.font.size=Pt(7.2);run.font.name='Times New Roman'
# prevent giant figures in narrow columns; inline shapes width 3.1in
for sh in doc.inline_shapes:
 if sh.width>Inches(3.1):sh.width=Inches(3.1)
# tables within column
COLUMN=3.1
for t in doc.tables:
 t.autofit=False
 ncols=len(t.columns)
 header=[c.text.strip() for c in t.rows[-1].cells]
 spacer=[i for i in range(ncols) if all(not r.cells[i].text.strip() for r in t.rows[2:])]
 first=1.0 if ncols<=7 else .78
 if t.rows[0].cells[0].text.strip()=='Workflow': first=.48
 widths=[]
 rest=[i for i in range(ncols) if i>0 and i not in spacer]
 for i in range(ncols):
  if i==0:widths.append(first)
  elif i in spacer:widths.append(.04)
  else:widths.append((COLUMN-first-.04*len(spacer)-(.72 if t.rows[0].cells[0].text.strip()=='Workflow' else 0))/max(1,len(rest)-(1 if t.rows[0].cells[0].text.strip()=='Workflow' else 0)))
 if t.rows[0].cells[0].text.strip()=='Workflow':widths[1]=.72
 if ncols==8 and t.rows[0].cells[0].text.strip()=='Condition':  # switching ablation: label, workflow, six values
  widths=[.66,.36]+[(COLUMN-1.02)/6]*6
 tblPr=t._tbl.tblPr
 for old in tblPr.findall(qn('w:tblW'))+tblPr.findall(qn('w:tblLayout')):tblPr.remove(old)
 tw=OxmlElement('w:tblW');tw.set(qn('w:w'),str(int(sum(widths)*1440)));tw.set(qn('w:type'),'dxa');tblPr.append(tw)
 lay=OxmlElement('w:tblLayout');lay.set(qn('w:type'),'fixed');tblPr.append(lay)
 for old in tblPr.findall(qn('w:tblCellMar')):tblPr.remove(old)
 mar=OxmlElement('w:tblCellMar')  # narrow side padding so short numeric columns do not wrap
 for side in ('left','right'):
  m=OxmlElement('w:'+side);m.set(qn('w:w'),'36');m.set(qn('w:type'),'dxa');mar.append(m)
 tblPr.append(mar)
 for gc,w in zip(t._tbl.tblGrid.findall(qn('w:gridCol')),widths):gc.set(qn('w:w'),str(int(w*1440)))
 for row in t.rows:
  for i,cell in enumerate(row.cells):
   cell.width=Inches(widths[i])
   for p in cell.paragraphs:
    p.paragraph_format.space_after=Pt(0)
    for run in p.runs:run.font.name='Times New Roman';run.font.size=Pt(6.5)
out=ROOT/'RetryBench_StratCom_Editable_Two_Column.docx'
doc.save(out)
print(out,len(doc.paragraphs),len(doc.tables),len(doc.inline_shapes))
