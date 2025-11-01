#!/bin/bash
set -e

echo "🕐 $(date +'%H:%M:%S') - Iniciando verificação de compatibilidade ultralytics..."
START_TIME=$(date +%s)

# Tenta primeiro a versão do requirements.txt
if pip install --no-cache-dir "ultralytics>=8.0.0,<9.0.0" && python3 check_c3k2.py; then
    echo "✅ $(date +'%H:%M:%S') - Compatibilidade verificada com ultralytics do requirements.txt"
    INSTALLED_VERSION=$(python3 -c "import ultralytics; print(ultralytics.__version__)" 2>/dev/null || echo "unknown")
    echo "📦 Versão instalada: $INSTALLED_VERSION"
else
    echo "⚠️  $(date +'%H:%M:%S') - Testando versões alternativas do ultralytics..."
    
    VERSIONS=("8.0.196" "8.0.100" "8.0.20" "8.1.0" "8.0.0" "7.1.0")
    VERSION_FOUND=false
    
    for version in "${VERSIONS[@]}"; do
        echo "→ $(date +'%H:%M:%S') - Tentando $version..."
        if pip install --no-cache-dir --force-reinstall "ultralytics==$version" && python3 check_c3k2.py; then
            echo "✅ $(date +'%H:%M:%S') - Compatível com ultralytics==$version"
            VERSION_FOUND=true
            break
        fi
    done
    
    # Se nenhuma versão funcionou
    if [ "$VERSION_FOUND" = false ]; then
        echo "❌ $(date +'%H:%M:%S') - Nenhuma versão testada é compatível!"
        echo "Versões testadas: requirements.txt, ${VERSIONS[*]}"
        echo "WARNING: O modelo best.pt pode precisar ser reexportado"
        exit 1
    fi
fi

END_TIME=$(date +%s)
DURATION=$((END_TIME - START_TIME))
echo "⏱️  Tempo total de instalação ultralytics: ${DURATION}s ($(($DURATION / 60))m $(($DURATION % 60))s)"

