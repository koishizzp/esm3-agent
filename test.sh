#!/bin/bash

echo "========================================="
echo "ESM3 Agent 测试"
echo "========================================="

# 测试1
echo ""
echo "1. 健康检查..."
curl -s http://localhost:8080/health
echo ""

# 测试2
echo ""
echo "2. 环境检查..."
curl -s http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"esm3-agent-v1","messages":[{"role":"user","content":"检查环境"}]}' \
  | jq -r '.choices[0].message.content'
echo ""

# 测试3
echo ""
echo "3. 序列分析..."
curl -s http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"esm3-agent-v1","messages":[{"role":"user","content":"分析序列 MKGEELFTGVV"}]}' \
  | jq -r '.choices[0].message.content'
echo ""

echo "========================================="
echo "测试完成"
echo "========================================="
