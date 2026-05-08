#!/bin/bash
# QHT Video Tools — Mac pe app start karne ke liye
# Double-click karo Finder mein

cd "$(dirname "$0")"

# Purana instance band karo (agar chal raha ho)
pkill -f "streamlit run app.py" 2>/dev/null

echo ""
echo "  ╔════════════════════════════════════════╗"
echo "  ║      QHT Video Tools starting...       ║"
echo "  ╚════════════════════════════════════════╝"
echo ""

# Local IP dhundho
LOCAL_IP=$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null)

echo "  Mac pe kholne ke liye:   http://localhost:8501"
if [ -n "$LOCAL_IP" ]; then
    echo "  Team ke liye (network):  http://${LOCAL_IP}:8501"
fi
echo ""
echo "  Band karne ke liye: Ctrl+C dabao ya yeh window close karo"
echo ""

streamlit run app.py --server.port 8501 --server.address 0.0.0.0
