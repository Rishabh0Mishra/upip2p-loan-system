from jinja2 import Environment, FileSystemLoader
from weasyprint import HTML
import os

TEMPLATE_DIR = "templates"
OUTPUT_DIR = "uploaded_docs"

env = Environment(loader=FileSystemLoader(TEMPLATE_DIR))

def generate_loan_agreement_pdf(loan_data: dict, output_filename: str) -> str:
    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)

    template = env.get_template("loan_agreement_template.html")
    html_out = template.render(loan=loan_data)

    output_path = os.path.join(OUTPUT_DIR, output_filename)
    HTML(string=html_out).write_pdf(output_path)
    return output_path
