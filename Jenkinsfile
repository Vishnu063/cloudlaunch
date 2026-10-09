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
                script {
                    sh 'docker tag cloudlaunch:latest cloudlaunch:new'

                    try {
                        sh '''
                            docker rm -f cloudlaunch || true
                            docker run -d \
                              --name cloudlaunch \
                              --restart unless-stopped \
                              -p 127.0.0.1:8080:80 \
                              cloudlaunch:new

                            sleep 5
                            for i in 1 2 3 4 5; do
                                curl --fail http://127.0.0.1:8080/ && exit 0
                                sleep 2
                            done
                            exit 1
                        '''
                    } catch (err) {
                        echo 'Deployment failed. Rolling back.'
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
