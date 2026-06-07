import ast
import os
from pathlib import Path

def find_bare_passes(directory):
    for root, _, files in os.walk(directory):
        if 'site-packages' in root or '.venv' in root or '__pycache__' in root:
            continue
        for file in files:
            if file.endswith('.py'):
                filepath = os.path.join(root, file)
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        content = f.read()
                    
                    tree = ast.parse(content, filename=filepath)
                    for node in ast.walk(tree):
                        if isinstance(node, ast.ExceptHandler):
                            # Check if the body only contains 'pass'
                            if len(node.body) == 1 and isinstance(node.body[0], ast.Pass):
                                exception_type = "Bare Exception"
                                if isinstance(node.type, ast.Name):
                                    exception_type = node.type.id
                                
                                # Log or print only if it's catching Exception
                                if exception_type == "Exception" or exception_type == "Bare Exception":
                                    print(f"File: {filepath}, Line: {node.lineno}, Type: {exception_type}")
                except Exception as e:
                    pass

if __name__ == '__main__':
    find_bare_passes('c:\\Users\\iyino\\Videos\\F1-project\\f1-project-backend\\backend\\api')
