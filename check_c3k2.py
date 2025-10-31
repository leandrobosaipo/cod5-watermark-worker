#!/usr/bin/env python3
"""Script para verificar compatibilidade do ultralytics com modelo YOLO."""
import sys
import os
from pathlib import Path

def check_model_compatibility():
    """
    Verifica se o ultralytics pode carregar o modelo YOLO.
    Tenta múltiplas estratégias:
    1. Verifica importação direta do C3k2 (método antigo)
    2. Verifica estrutura de módulos
    3. Tenta carregar modelo de teste (se disponível)
    """
    try:
        import ultralytics
        version = ultralytics.__version__
        print(f"Ultralytics version: {version}", file=sys.stderr)
        
        # Estratégia 1: Tentar importação direta do C3k2
        try:
            # Versões mais antigas (8.0.0, 8.0.100)
            from ultralytics.nn.modules.block import C3k2
            print("✓ C3k2 encontrado via ultralytics.nn.modules.block", file=sys.stderr)
            return True
        except (ImportError, AttributeError, ModuleNotFoundError):
            pass
        
        # Estratégia 2: Verificar estrutura alternativa
        try:
            # Algumas versões podem ter estrutura diferente
            from ultralytics.nn.modules import block
            if hasattr(block, 'C3k2'):
                print("✓ C3k2 encontrado em ultralytics.nn.modules.block (alternativa)", file=sys.stderr)
                return True
        except (ImportError, AttributeError, ModuleNotFoundError):
            pass
        
        # Estratégia 3: Verificar se o YOLO pode importar (sem modelo)
        try:
            from ultralytics import YOLO
            # Verifica se o YOLO está funcional
            print("✓ YOLO importável", file=sys.stderr)
            
            # Estratégia 4: Se modelo existe, tentar carregar
            model_path = "/app/models/best.pt"
            if os.path.exists(model_path):
                try:
                    # Tenta carregar modelo (sem executar)
                    # Isso vai falhar se C3k2 não estiver disponível
                    model = YOLO(model_path, verbose=False)
                    print("✓ Modelo YOLO carregável", file=sys.stderr)
                    return True
                except Exception as model_error:
                    error_str = str(model_error)
                    if 'C3k2' in error_str or 'block' in error_str.lower():
                        print(f"✗ Modelo requer C3k2 mas não está disponível: {error_str}", file=sys.stderr)
                        return False
                    else:
                        # Outro tipo de erro - modelo pode estar corrompido, mas C3k2 não é o problema
                        print(f"⚠ Erro ao carregar modelo (pode ser outro problema): {error_str}", file=sys.stderr)
                        # Se não é erro de C3k2, consideramos OK
                        return True
            else:
                # Modelo não existe ainda (durante build do Docker)
                # Se YOLO importa, provavelmente está OK
                print("⚠ Modelo não encontrado, mas YOLO está funcional", file=sys.stderr)
                return True
                
        except Exception as e:
            print(f"✗ Erro ao verificar YOLO: {e}", file=sys.stderr)
            return False
            
    except ImportError as e:
        print(f"✗ Erro ao importar ultralytics: {e}", file=sys.stderr)
        return False
    except Exception as e:
        print(f"✗ Erro inesperado: {e}", file=sys.stderr)
        return False

if __name__ == "__main__":
    success = check_model_compatibility()
    sys.exit(0 if success else 1)
