pipeline {
    agent any

    stages {
        stage('Checkout') {
            steps {
                git branch: 'main',
                    url: 'https://github.com/Vishnu063/cloudlaunch.git'
            }
        }

        stage('Validate') {
            steps {
                sh 'test -s site/index.html'
                sh 'test -s Dockerfile'
            }
        }

        stage('Build Image') {
            steps {
                sh 'docker build -t cloudlaunch:latest .'
            }
        }

        stage('Deploy') {
            steps {
                sh '''
                    docker rm -f cloudlaunch
                    docker run -d \
                      --name cloudlaunch \
                      --restart unless-stopped \
                      -p 127.0.0.1:8080:80 \
                      cloudlaunch:latest
                '''
            }
        }

        stage('Health Check') {
            steps {
                sh 'curl --fail --retry 5 --retry-connrefused --retry-delay 2 http://127.0.0.1:8080/'
                echo 'Website health check passed'
            }
        }
    }
}
