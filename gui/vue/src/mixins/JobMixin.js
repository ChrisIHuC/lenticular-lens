export default {
    data() {
        return {
            job: null,
            linksets: [],
            lenses: [],
            clusterings: [],
            entityTypeSelections: [],
            linksetSpecs: [],
            lensSpecs: [],
            datasets: {},
            downloaded: [],
            downloading: [],
            associationFiles: [],
        };
    },
    methods: {
        getDatasets(graphqlEndpoint, hsid) {
            const id = graphqlEndpoint && hsid ? graphqlEndpoint + ':' + hsid : graphqlEndpoint;
            return this.datasets.hasOwnProperty(id) ? this.datasets[id] : {};
        },

        addEntityTypeSelection() {
            this.entityTypeSelections.unshift({
                id: findId(this.entityTypeSelections),
                description: '',
                dataset: {
                    dataset_id: '',
                    collection_id: '',
                    published: true,
                    timbuctoo_graphql: 'https://repository.goldenagents.org/v5/graphql',
                    timbuctoo_hsid: null,
                },
                filter: {
                    type: 'AND',
                    conditions: [],
                },
                limit: -1,
                random: false,
                properties: [],
                related: [],
                related_array: false,
            });
        },

        addLinksetSpec() {
            this.linksetSpecs.unshift({
                id: findId(this.linksetSpecs),
                label: 'Linkset ' + (this.linksetSpecs.length + 1),
                description: '',
                is_association: false,
                sources: [],
                targets: [],
                methods: {
                    type: 'AND',
                    conditions: [],
                },
                properties: []
            });
        },

        addLensSpec() {
            this.lensSpecs.unshift({
                id: findId(this.lensSpecs),
                label: 'Lens ' + (this.lensSpecs.length + 1),
                description: '',
                specs: {
                    type: 'UNION',
                    elements: [],
                },
                properties: []
            });
        },

        duplicateEntityTypeSelection(entityTypeSelection) {
            const index = this.entityTypeSelections.findIndex(res => res.id === entityTypeSelection.id);
            const duplicate = copy(entityTypeSelection);
            this.entityTypeSelections.splice(index, 0, {
                ...duplicate,
                id: findId(this.entityTypeSelections),
                label: undefined,
            });
        },

        duplicateLinksetSpec(linksetSpec) {
            const index = this.linksetSpecs.findIndex(m => m.id === linksetSpec.id);
            const duplicate = copy(linksetSpec);
            this.linksetSpecs.splice(index, 0, {
                ...duplicate,
                id: findId(this.linksetSpecs),
                label: 'Linkset ' + (this.linksetSpecs.length + 1),
            });
        },

        duplicateLensSpec(lensSpec) {
            const index = this.lensSpecs.findIndex(m => m.id === lensSpec.id);
            const duplicate = copy(lensSpec);
            this.lensSpecs.splice(index, 0, {
                ...duplicate,
                id: findId(this.lensSpecs),
                label: 'Lens ' + (this.lensSpecs.length + 1),
            });
        },

        getEntityTypeSelectionById(id) {
            return this.entityTypeSelections.find(res => res.id === parseInt(id));
        },

        getLinksetSpecById(id) {
            return this.linksetSpecs.find(linksetSpec => linksetSpec.id === parseInt(id));
        },

        getLensSpecById(id) {
            return this.lensSpecs.find(lensSpec => lensSpec.id === parseInt(id));
        },

        getCleanPropertyName(property, propInfo) {
            if (propInfo.isList)
                property = property.replace(/List$/, '');
            if (propInfo.isInverse)
                property = property.replace(/^_inverse_/, '');

            return property;
        },

        exportCsvLink(type, id, accepted, rejected, notValidated, mixed) {
            const params = [];
            if (accepted) params.push('valid=accepted');
            if (rejected) params.push('valid=rejected');
            if (notValidated) params.push('valid=not_validated');
            if (mixed) params.push('valid=mixed');

            return `/job/${this.job.job_id}/export/${type}/${id}/csv?${params.join('&')}`;
        },

        getRecursiveElements(elementsGroup, groupName) {
            let elements;
            if (Array.isArray(elementsGroup))
                elements = elementsGroup;
            else if (Array.isArray(elementsGroup[groupName]))
                elements = elementsGroup[groupName];

            if (elements)
                return elements.reduce((acc, element) => acc.concat(this.getRecursiveElements(element, groupName)), []);

            return [elementsGroup];
        },

        async submit() {
            await this.updateJob({
                job_id: this.job.job_id,
                job_title: this.job.job_title,
                job_description: this.job.job_description,
                job_link: this.job.job_link,
                entity_type_selections: this.entityTypeSelections,
                linkset_specs: this.linksetSpecs,
                lens_specs: this.lensSpecs,
            });
        },

        async loadJob(id) {
            const job = await callApi('/job/' + id);
            if (!job)
                return;

            job.created_at = job.created_at ? new Date(job.created_at) : null;
            job.updated_at = job.updated_at ? new Date(job.updated_at) : null;
            this.job = job;

            if (this.job.entity_type_selections) {
                const entityTypeSelections = copy(this.job.entity_type_selections);

                const graphQlEndpoints = entityTypeSelections
                    .map(ets => ({endpoint: ets.dataset.timbuctoo_graphql, hsid: ets.dataset.timbuctoo_hsid}))
                    .sort((dataA, dataB) => {
                        if (dataA.hsid && !dataB.hsid) return -1;
                        if (dataB.hsid && !dataA.hsid) return 1;
                        return 0;
                    })
                    .filter((data, idx, res) => res.findIndex(data2 => data2.endpoint === data.endpoint) === idx);
                await Promise.all(graphQlEndpoints.map(data => this.loadDatasets(data.endpoint, data.hsid)));

                this.entityTypeSelections = entityTypeSelections;
            }

            if (this.job.linkset_specs)
                this.linksetSpecs = copy(this.job.linkset_specs);

            if (this.job.lens_specs)
                this.lensSpecs = copy(this.job.lens_specs);

            await Promise.all([this.loadLinksets(), this.loadLenses(), this.loadClusterings()]);
        },

        async loadLinksets() {
            const linksets = await callApi(`/job/${this.job.job_id}/linksets`);
            linksets.forEach(linkset => {
                linkset.requested_at = linkset.requested_at ? new Date(linkset.requested_at) : null;
                linkset.processing_at = linkset.processing_at ? new Date(linkset.processing_at) : null;
                linkset.finished_at = linkset.finished_at ? new Date(linkset.finished_at) : null;
            });
            this.linksets = linksets;
        },

        async loadLenses() {
            const lenses = await callApi(`/job/${this.job.job_id}/lenses`);
            lenses.forEach(lens => {
                lens.requested_at = lens.requested_at ? new Date(lens.requested_at) : null;
                lens.processing_at = lens.processing_at ? new Date(lens.processing_at) : null;
                lens.finished_at = lens.finished_at ? new Date(lens.finished_at) : null;
            });
            this.lenses = lenses;
        },

        async loadClusterings() {
            const clusterings = await callApi(`/job/${this.job.job_id}/clusterings`);
            clusterings.forEach(clustering => {
                clustering.requested_at = clustering.requested_at ? new Date(clustering.requested_at) : null;
                clustering.processing_at = clustering.processing_at ? new Date(clustering.processing_at) : null;
                clustering.finished_at = clustering.finished_at ? new Date(clustering.finished_at) : null;
            });
            this.clusterings = clusterings;
        },

        async createJob(inputs) {
            const data = await callApi('/job/create/', inputs);
            return data.job_id;
        },

        async updateJob(jobData) {
            return callApi('/job/update/', jobData);
        },

        async runLinkset(id, restart) {
            await this.submit();
            return callApi(`/job/${this.job.job_id}/run_linkset/${id}`, {restart});
        },

        async runLens(id, restart) {
            await this.submit();
            return callApi(`/job/${this.job.job_id}/run_lens/${id}`, {restart});
        },

        async runClustering(type, id, associationFile) {
            return callApi(`/job/${this.job.job_id}/run_clustering/${type}/${id}`,
                {association_file: associationFile});
        },

        async killLinkset(id) {
            return callApi(`/job/${this.job.job_id}/kill_linkset/${id}`, {});
        },

        async killLens(id) {
            return callApi(`/job/${this.job.job_id}/kill_lens/${id}`, {});
        },

        async killClustering(type, id) {
            return callApi(`/job/${this.job.job_id}/kill_clustering/${type}/${id}`, {});
        },

        async getEntityTypeSelectionSampleTotal(label) {
            return callApi(`/job/${this.job.job_id}/entity_type_selection_total/${label}`);
        },

        async getEntityTypeSelectionSample(label, invert = false, limit = undefined, offset = 0) {
            const params = [];
            if (invert) params.push(`invert=${invert}`);
            if (limit) params.push(`limit=${limit}`);
            if (offset) params.push(`offset=${offset}`);

            return callApi(`/job/${this.job.job_id}/entity_type_selection/${label}?${params.join('&')}`);
        },

        async getLinksTotals(type, id, clusterId = undefined) {
            const params = [];
            if (clusterId) params.push(`cluster_id=${clusterId}`);

            return callApi(`/job/${this.job.job_id}/links_totals/${type}/${id}?${params.join('&')}`);
        },

        async getLinks(type, id, accepted, rejected, notValidated, mixed, clusterId = undefined,
                       limit = undefined, offset = 0) {
            const params = [];
            if (accepted) params.push('valid=accepted');
            if (rejected) params.push('valid=rejected');
            if (notValidated) params.push('valid=not_validated');
            if (mixed) params.push('valid=mixed');
            if (clusterId) params.push(`cluster_id=${clusterId}`);
            if (limit) params.push(`limit=${limit}`);
            if (offset) params.push(`offset=${offset}`);

            return callApi(`/job/${this.job.job_id}/links/${type}/${id}?${params.join('&')}`);
        },

        async getClusters(type, id, association, limit = undefined, offset = 0) {
            const params = [];
            if (association) params.push(`association=${association}`);
            if (limit) params.push(`limit=${limit}`);
            if (offset) params.push(`offset=${offset}`);

            return callApi(`/job/${this.job.job_id}/clusters/${type}/${id}?${params.join('&')}`);
        },

        async getClusterGraphs(type, id, clusterId, getCluster = undefined,
                               getClusterCompact = undefined, getReconciliation = undefined) {
            const params = [];
            if (getCluster !== undefined) params.push(`get_cluster=${getCluster}`);
            if (getClusterCompact !== undefined) params.push(`get_cluster_compact=${getClusterCompact}`);
            if (getReconciliation !== undefined) params.push(`get_reconciliation=${getReconciliation}`);

            return callApi(`/job/${this.job.job_id}/cluster/${type}/${id}/${clusterId}/graph?${params.join('&')}`);
        },

        async validateLink(type, id, source, target, valid) {
            return callApi(`/job/${this.job.job_id}/validate/${type}/${id}`, {source, target, valid});
        },

        async loadDatasets(graphqlEndpoint, hsid) {
            const id = graphqlEndpoint && hsid ? graphqlEndpoint + ':' + hsid : graphqlEndpoint;
            if (!id || this.datasets.hasOwnProperty(id))
                return;

            const params = [`endpoint=${graphqlEndpoint}`];
            if (hsid) params.push(`hsid=${hsid}`);

            this.datasets[id] = await callApi(`/datasets?${params.join('&')}`);

            if (hsid) {
                const datasetsPublished = {};

                Object.keys(this.datasets[id]).forEach(datasetName => {
                    const dataset = this.datasets[id][datasetName];
                    if (dataset.published)
                        datasetsPublished[datasetName] = dataset;
                });

                this.datasets[graphqlEndpoint] = datasetsPublished;
            }
        },

        async startDownload(datasetId, collectionId, graphqlEndpoint, hsid) {
            const params = [`dataset_id=${datasetId}`, `collection_id=${collectionId}`, `endpoint=${graphqlEndpoint}`];
            if (hsid) params.push(`hsid=${hsid}`);

            return callApi(`/download?${params.join('&')}`);
        },

        async loadDownloadsInProgress() {
            const downloads = await callApi('/downloads');
            this.downloaded = downloads.downloaded;
            this.downloading = downloads.downloading;
        },

        async loadAssociationFiles() {
            this.associationFiles = await callApi('/association_files');
        },
    },
};

function copy(obj) {
    return JSON.parse(JSON.stringify(obj));
}

function findId(objs) {
    let latestId = -1;
    objs.forEach(obj => {
        if (obj.id > latestId) latestId = obj.id;
    });
    return latestId + 1;
}

async function callApi(path, body) {
    try {
        let response;

        if (body) {
            response = await fetch(path, {
                headers: {
                    'Accept': 'application/json',
                    'Content-Type': 'application/json',
                },
                method: 'POST',
                body: JSON.stringify(body)
            });
        }
        else {
            response = await fetch(path);
        }

        if (!response.ok)
            return null;

        return response.json();
    }
    catch (e) {
        return null;
    }
}