from starlette.exceptions import HTTPException
import logging
import json

logger = logging.getLogger('starqueue')
logger.debug('CleanRequest')

class CleanRequest():

    async def clean(self, request, required_fields, optional_fields):
        data_to_clean = await self.make_data_to_clean(request, required_fields, optional_fields)
        await self.ensure_required_fields_present(data_to_clean, required_fields)
        data_to_clean = await self.ensure_optional_fields_present(data_to_clean, optional_fields)
        await self.ensure_no_unknown_fields(data_to_clean, optional_fields + required_fields)
        return data_to_clean

    async def ensure_required_fields_present(self, data_to_clean, required_fields):
        for field_name in required_fields:
            if field_name not in data_to_clean.keys():
                raise HTTPException(400, detail=f'missing required field: {field_name}')

    async def ensure_optional_fields_present(self, data_to_clean, optional_fields):
        # All fields must be in the data_to_clean including optional fields
        for field_name in optional_fields:
            if field_name not in data_to_clean.keys():
                data_to_clean[field_name] = None
        return data_to_clean

    async def ensure_no_unknown_fields(self, data_to_clean, all_fields):
        for field_name in data_to_clean.keys():
            if field_name not in all_fields:
                raise HTTPException(400, detail=f'Request may not include unknown fields: {field_name}')

    async def get_ipaddress(self, request):
        #########################################
        # tries all the common ways of getting an IP address
        #########################################
        try:
            if request.headers['X-Forwarded-For'] is not None:
                return request.headers['X-Forwarded-For']
        except:
            pass

        try:
            if request.client.host is not None:
                return request.client.host
        except:
            pass

        return 'unknown'


    async def make_metadata(self, request):
        metadata = {}
        metadata['ipaddress'] = await self.get_ipaddress(request)
        return json.dumps(metadata)

    async def get_request_fields(self, request):
        try:
            form = await request.json()
            return form
        except:
            raise HTTPException(400, detail=f'POST data must be valid json')

    async def make_data_to_clean(self, request, required_fields, optional_fields):
        '''
        This gathers the fields from the POST json plus the URL fields and puts them in a single structure.
        '''
        logger.debug('STD make_data_to_clean')

        # get the form fields
        data_to_clean = await self.get_request_fields(request)

        # get values from headers
        if 'contenttype'in required_fields + optional_fields:
            data_to_clean['contenttype'] = request.headers.get('content-type')

        # get values from the URL
        if 'accountid'in required_fields + optional_fields:
            data_to_clean['accountid'] = request.path_params.get('accountid', None)
        if 'queuename'in required_fields + optional_fields:
            data_to_clean['queuename'] = request.path_params.get('queuename', None)
        if 'metadata'in required_fields + optional_fields:
            data_to_clean['metadata'] = await self.make_metadata(request)
        if 'ipaddress'in required_fields + optional_fields:
            data_to_clean['ipaddress'] = await self.get_ipaddress(request)

        return data_to_clean


