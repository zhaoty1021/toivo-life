# input/

放候选人简历原文 (纯文本 / markdown)。命名建议:
- `<name>_resume.txt` 单人使用
- `<name>_<version>.txt` 需要迭代对比时

不要放 PDF 或 docx —— 先自行导出为文本再放进来。

CLI 用:
```
python -m toivo run career_resume --input input/<name>_resume.txt --output output/<name>_diagnosis.pdf
```
