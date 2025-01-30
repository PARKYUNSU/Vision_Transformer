import torch
import torch.optim as optim
from model.vit import Vision_Transformer
from data import cifar_10
from utils import save_model

def train(model, train_loader, test_loader, epochs, learning_rate, device):
    criterion = torch.nn.CrossEntropyLoss()
    optimizer = optim.Adam(model.parameters(), lr=learning_rate)

    # 모델을 CUDA로 올림
    model = model.to(device)

    for epoch in range(epochs):
        model.train()
        running_loss = 0.0
        for inputs, labels in train_loader:
            inputs, labels = inputs.to(device), labels.to(device)  # 데이터도 CUDA로 이동
            
            optimizer.zero_grad()
            outputs = model(inputs)
            loss = criterion(outputs, labels)
            loss.backward()
            optimizer.step()

            running_loss += loss.item()

        print(f'Epoch [{epoch+1}/{epochs}], Loss: {running_loss/len(train_loader):.4f}')
        evaluate(model, test_loader, device)
        
    print('Training finished.')

def evaluate(model, test_loader, device):
    model.eval()
    correct = 0
    total = 0
    with torch.no_grad():
        for inputs, labels in test_loader:
            inputs, labels = inputs.to(device), labels.to(device)  # 데이터도 CUDA로 이동
            outputs = model(inputs)
            _, predicted = torch.max(outputs.data, 1)
            total += labels.size(0)
            correct += (predicted == labels).sum().item()
    
    print(f'Accuracy: {100 * correct / total:.2f}%')

def main(pretrained_path, epochs, batch_size, learning_rate):
    # device 설정 (cuda 사용 가능하면 cuda, 아니면 cpu)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    
    model = Vision_Transformer(img_size=224, num_classes=10, in_channels=3, pretrained=True, pretrained_path=pretrained_path)
    
    # cifar_10 데이터셋 로드
    train_loader, test_loader = cifar_10(batch_size)
    
    # 학습 시작
    train(model, train_loader, test_loader, epochs, learning_rate, device)

if __name__ == "__main__":
    pass