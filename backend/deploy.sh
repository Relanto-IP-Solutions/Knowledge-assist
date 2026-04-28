echo "Building new image..."
docker build -t main-backend .
 
echo "Stopping old container..."
docker stop main-backend 2>/dev/null || true
docker rm main-backend 2>/dev/null || true
 
echo "Starting new container..."
docker run -d -p 8000:8000 --name main-backend main-backend
 
echo "Done! Running containers:"
docker ps --filter "name=main-backend"