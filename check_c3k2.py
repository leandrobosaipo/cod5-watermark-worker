#!/usr/bin/env python3
"""Script para verificar se C3k2 está disponível no ultralytics."""
import sys

def check_c3k2():
    """Verifica se C3k2 está disponível."""
    try:
        import ultralytics
        version = ultralytics.__version__
        print(f"Ultralytics version: {version}", file=sys.stderr)
        
        # Tenta importar C3k2
        from ultralytics.nn.modules.block import C3k2
        print("C3k2 module found!", file=sys.stderr)
        return True
    except ImportError as e:
        print(f"C3k2 not found (ImportError): {e}", file=sys.stderr)
        return False
    except AttributeError as e:
        print(f"C3k2 not found (AttributeError): {e}", file=sys.stderr)
        return False
    except Exception as e:
        print(f"Error checking C3k2: {e}", file=sys.stderr)
        return False

if __name__ == "__main__":
    success = check_c3k2()
    sys.exit(0 if success else 1)
