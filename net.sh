# 安装 .NET 8.0
wget https://packages.microsoft.com/config/ubuntu/$(lsb_release -rs)/packages-microsoft-prod.deb -O packages-microsoft-prod.deb
sudo dpkg -i packages-microsoft-prod.deb
rm packages-microsoft-prod.deb

# 安装 SDK
sudo apt-get update
sudo apt-get install -y dotnet-sdk-8.0

# 验证安装
dotnet --version

# 如果还是找不到，添加 PATH
export PATH="$PATH:$HOME/.dotnet"
echo 'export PATH="$PATH:$HOME/.dotnet"' >> ~/.bashrc
