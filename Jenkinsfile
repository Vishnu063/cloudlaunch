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

        stage('Backup Previous Image') {
            steps {
                sh '''
                    docker tag \
                      "$(docker inspect --format='{{.Image}}' cloudlaunch)" \
                      cloudlaunch:previous
                '''
            }
        }

        stage('Build Image') {
            steps {
                sh 'docker build -t cloudlaunch:latest .'
            }
        }

        stage('Deploy') {
            steps {
                script {
                    try {
                        sh '''
                            docker rm -f cloudlaunch
                            docker run -d \
                              --name cloudlaunch \
                              --restart unless-stopped \
                              -p 127.0.0.1:8080:80 \
                              cloudlaunch:latest

                            for i in $(seq 1 15); do
                                status=$(docker inspect \
                                  --format='{{.State.Health.Status}}' cloudlaunch)
                                [ "$status" = "healthy" ] && exit 0
                                sleep 2
                            done
                            exit 1
                        '''
                    } catch (err) {
                        echo 'Deployment failed; restoring previous image.'
                        sh '''
                            docker rm -f cloudlaunch || true
                            docker run -d \
                              --name cloudlaunch \
                              --restart unless-stopped \
                              -p 127.0.0.1:8080:80 \
                              cloudlaunch:previous
                        '''
                        error('Deployment failed; rollback attempted.')
                    }
                }
            }
        }
    }
}
