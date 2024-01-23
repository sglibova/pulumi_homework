import os
import pulumi
import pulumi_docker as docker
import pulumi_aws as aws
import pulumi_awsx as awsx
import pulumi_eks as eks
import pulumi_kubernetes as k8s

from pulumi import ComponentResource, CustomTimeouts

# Get some values from the Pulumi configuration (or use defaults)
config = pulumi.Config()

# Docker Image Config
config_color = config.get("config_color", "red")

# ECR Config
ecr_user=config.get("ecrUser")
ecr_repo_name = "web-server"

# TODO: Require Config object to be passed in during class instantiation.
# EKS Cluster Component Resource
class EKSCluster(ComponentResource):
    def __init__(self, cluster_name, vpc_name, opts = None):
        super().__init__('sglibova:aws:EKSCluster', cluster_name, None, opts)

        config=pulumi.Config()
        
        # EKS Config
        min_cluster_size = config.get_float("minClusterSize", 3)
        max_cluster_size = config.get_float("maxClusterSize", 6)
        desired_cluster_size = config.get_float("desiredClusterSize", 3)
        eks_node_instance_type = config.get("eksNodeInstanceType", "t3.medium")

        # VPC Config
        vpc_network_cidr = config.get("vpcNetworkCidr", "10.0.0.0/16")

        # Create a VPC for the EKS cluster
        eks_vpc = awsx.ec2.Vpc(vpc_name,
            enable_dns_hostnames=True,
            cidr_block=vpc_network_cidr, 
            opts=pulumi.ResourceOptions(parent=self))

        # Create the EKS cluster
        eks_cluster = eks.Cluster(cluster_name,
            # Put the cluster in the new VPC created earlier
            vpc_id=eks_vpc.vpc_id,
            # Public subnets will be used for load balancers
            public_subnet_ids=eks_vpc.public_subnet_ids,
            # Private subnets will be used for cluster nodes
            private_subnet_ids=eks_vpc.private_subnet_ids,
            # Change configuration values to change any of the following settings
            instance_type=eks_node_instance_type,
            desired_capacity=desired_cluster_size,
            min_size=min_cluster_size,
            max_size=max_cluster_size,
            # Do not give worker nodes a public IP address
            node_associate_public_ip_address=False,
            # Change these values for a private cluster (VPN access required)
            endpoint_private_access=False,
            endpoint_public_access=True,
            opts=pulumi.ResourceOptions(parent=self)
        
    )
        # Unsure here
        # Needed aws_provider attribute to pass to K8s deployment
        self.aws_provider = eks_cluster.aws_provider
        self.register_outputs({
            "vpcId": eks_vpc.vpc_id,
            "kubeconfig": eks_cluster.kubeconfig
        })
        # This works
        pulumi.export("vpcId", eks_vpc.vpc_id)
        pulumi.export("kubeconfig", eks_cluster.kubeconfig)

# Kubernetes Deployment and Service Class
# This depends on cluster creation - unsure of how to set this order up.
class K8sDeployment(ComponentResource):
    def __init__(self, app_name, app_image, service_name, opts = None):
        super().__init__('sglibova:aws:K8sDeployment', app_name, None, opts)
        
        app_labels = {'app': app_name }
        deployment = k8s.apps.v1.Deployment(app_name,
                                            metadata=k8s.meta.v1.ObjectMetaArgs(labels=app_labels),
                                            spec=k8s.apps.v1.DeploymentSpecArgs(
                                                replicas=3,
                                                selector=k8s.meta.v1.LabelSelectorArgs(match_labels=app_labels),
                                                template=k8s.core.v1.PodTemplateSpecArgs(
                                                    metadata=k8s.meta.v1.ObjectMetaArgs(
                                                        labels=app_labels,
                                                        namespace=app_name),
                                                    spec=k8s.core.v1.PodSpecArgs(
                                                        containers=[
                                                            k8s.core.v1.ContainerArgs(
                                                                name='flask-server',
                                                                image=f"{app_image}",
                                                                ports=[k8s.core.v1.ContainerPortArgs(container_port=5000, host_port=5000)]
                                                            )
                                                        ]
                                                    )
                                                )
                                            ),
                                            opts=pulumi.ResourceOptions(
                                                provider=eks_cluster.aws_provider,
                                                parent=self,
                                                custom_timeouts=CustomTimeouts(create='5m'))
                                            )

        # Create a Kubernetes Service
        service = k8s.core.v1.Service(service_name, spec=k8s.core.v1.ServiceSpecArgs(
            ports=[k8s.core.v1.ServicePortArgs(
                port=5000,
                protocol="TCP",
                target_port=5000,
            )],
            selector={
                "app": "web-server",
            },
        ),
            opts=pulumi.ResourceOptions(provider=eks_cluster.aws_provider,
                                        parent=self,
                                        custom_timeouts=CustomTimeouts(create='6m')))
        
        # Register Outputs
        self.register_outputs({
            "serviceUrl": service.status.apply(
            lambda status: status['load_balancer']['ingress'][0].get('hostname') or
            status['load_balancer']['ingress'][0].get('ip'))
        })
        # Alternatively, use Pulumi to export within the class
        pulumi.export("serviceStatus", service.status)
        pulumi.export("serviceUrl", service.status.apply(
            lambda status: status['load_balancer']['ingress'][0].get('hostname') or
            status['load_balancer']['ingress'][0].get('ip')
))
     
# Create an ECR resource for the Docker image built above
ecr_repo = aws.ecr.Repository(ecr_repo_name, name="flask-server")
auth_token = aws.ecr.get_authorization_token_output(registry_id=ecr_repo.registry_id)

# Build backend Image
backend_image = docker.Image("flask-server",
                        build=docker.DockerBuildArgs(
                            args={
                                "platform":"linux/arm64",
                                "env": f"CONFIG_COLOR={config_color}"
                            },
                            context=f"{os.getcwd()}/app"),
                        image_name=ecr_repo.repository_url.apply(lambda repository_url: f"{repository_url}:latest"),
                        skip_push=True

        # Trouble authenticating here, so pushed manually

                        # registry=docker.RegistryArgs(
        # username=auth_token.user_name,
        # password=pulumi.Output.secret(auth_token.password),
        # server=ecr_repo.repository_url,
        )

# Create an EKS Cluster
eks_cluster = EKSCluster(cluster_name="web-server-cluster", vpc_name="web-server-vpc")

# Create a Kubernetes Deployment and Service
k8s_deployment = K8sDeployment(app_name="web-server",
                               app_image=f"785847918082.dkr.ecr.us-east-2.amazonaws.com/flask-server:latest",
                               service_name="web-server-service")

# Export values to use elsewhere
pulumi.export("ecrRepoUrl", ecr_repo.repository_url)


