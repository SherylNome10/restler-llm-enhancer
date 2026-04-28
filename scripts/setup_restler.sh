#!/bin/bash

# RESTler macOS 安装脚本
set -e

echo "========================================="
echo "Installing RESTler on macOS..."
echo "========================================="

# 检查 Homebrew
if ! command -v brew &> /dev/null; then
    echo "Installing Homebrew..."
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
fi

# 安装 .NET 8.0
if ! command -v dotnet &> /dev/null; then
    echo "Installing .NET 8.0..."
    brew install dotnet-sdk
else
    echo ".NET already installed: $(dotnet --version)"
fi

# 创建目录
RESTLER_DIR="./data/restler"
mkdir -p $RESTLER_DIR

# 下载 RESTler
cd $RESTLER_DIR

if [ ! -d "restler-fuzzer" ]; then
    echo "Downloading RESTler..."
    git clone --depth 1 https://github.com/microsoft/restler-fuzzer.git
else
    echo "RESTler already downloaded"
fi

# 构建 RESTler
echo "Building RESTler..."
cd restler-fuzzer
dotnet build -c Release

# 创建软链接
ln -sf "$(pwd)/restler/Restler/bin/Release/net6.0/Restler" ../Restler

cd ../..

echo "========================================="
echo "Setup complete!"
echo "========================================="
