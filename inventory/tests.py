from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from selenium.webdriver.common.action_chains import ActionChains
from django.test import tag
from selenium import webdriver
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image
import io
from .models import Item
from pyzbar.pyzbar import decode
from io import BytesIO
import base64
from selenium.common.exceptions import NoSuchElementException
from django.contrib.auth.models import User
from tests.selenium_helpers import get_chrome_options, login_from_page
from django.test import TestCase


class HomepageTileTests(TestCase):
    def test_kitchen_inventory_tile_hidden(self):
        user = User.objects.create_user(username='u', password='p')
        self.client.force_login(user)
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'inventory/hub/icon.svg')
        self.assertNotContains(response, 'Kitchen Inventory')

@tag('selenium')
class ItemModalTests(StaticLiveServerTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.browser = webdriver.Chrome(options=get_chrome_options())
        cls.browser.set_window_size(1920, 1080)

    @classmethod
    def tearDownClass(cls):
        cls.browser.quit()
        super().tearDownClass()

    def setUp(self):
        # Reset browser state between tests
        self.browser.get('about:blank')
        self.browser.delete_all_cookies()

        # Create a white square placeholder image in memory
        image = Image.new('RGB', (100, 100), color='black')
        image_io = io.BytesIO()
        image.save(image_io, format='PNG')

        #create 12 items and assign them to an array called items
        self.items = []
        for i in range(1, 13):
            image_file = SimpleUploadedFile(f'test_image_{i}.png', image_io.getvalue(), content_type="image/png")
            
            if i <= 6:
              item = Item.objects.create(
                  name=f"Item {i}",
                  description=f"This is item {i}",
                  room="Living Room",
                  desc_long=f"A long description of item {i}.",
                  picture=image_file
              )
            else:
              item = Item.objects.create(
                  name=f"Item {i}",
                  description=f"This is item {i}",
                  room="Bedroom",
                  picture=image_file
              )
            
            self.items.append(item)
            
        self.test_user = User.objects.create_user(username='testuser', password='testpassword', is_staff=True)            
            
    def tearDown(self):
        # Clean up the test image files
        for item in self.items:
            item.picture.delete()
            
    def test_home_button_brings_user_to_home_page(self):
        # Navigate to the inventory page
        self.browser.get(f'{self.live_server_url}/inventory/')
        
        #wait for first tile to load
        item_element = WebDriverWait(self.browser, 20).until(
            EC.element_to_be_clickable((By.ID, f'item-{self.items[1].id}'))
        )
        
        #click the home button
        home_button = self.browser.find_element(By.ID, 'home-button')
        home_button.click()
        
        #check that the user is on the home page
        self.assertEqual(self.browser.current_url, f'{self.live_server_url}/')
        
    def test_all_inventory_items_are_displayed(self):
        # Navigate to the inventory page
        self.browser.get(f'{self.live_server_url}/inventory/')
        
        #wait for first tile to load
        item_element = WebDriverWait(self.browser, 20).until(
            EC.element_to_be_clickable((By.ID, f'item-{self.items[1].id}'))
        )
        
        #count the number of items displayed
        items = self.browser.find_elements(By.CSS_SELECTOR, "[id^='item-']")
        self.assertEqual(len(items), 13, "There should be 13 items displayed")                    

    def test_modal_opens_and_displays_content_with_image(self, check_edit_button=False):
        # Navigate to the inventory page
        self.browser.get(f'{self.live_server_url}/inventory/')
        
        #wait for first tile to load
        item_element = WebDriverWait(self.browser, 20).until(
            EC.element_to_be_clickable((By.ID, f'item-{self.items[1].id}'))
        )
        
        item_element.click()
        
        # Wait for the modal to appear
        WebDriverWait(self.browser, 20).until(
            EC.visibility_of_element_located((By.ID, 'itemModal'))
        )
        
        # Wait until the title of the modal is populated (indicating the modal is fully loaded)
        WebDriverWait(self.browser, 20).until(
            lambda driver: driver.find_element(By.ID, 'modal-item-title').text != ''
        )
        
        # Check modal content
        modal_title = self.browser.find_element(By.ID, 'modal-item-title').text
        self.assertEqual(modal_title, "Item 2")
                
        #check room heading
        modal_room_heading = self.browser.find_element(By.ID, 'modal-item-room-heading').text
        self.assertEqual(modal_room_heading, "Room")
                
        #check room text
        modal_room = self.browser.find_element(By.ID, 'modal-item-room').text
        self.assertEqual(modal_room, "Living Room")
        
        #check description heading
        modal_description_heading = self.browser.find_element(By.ID, 'modal-item-description-heading').text
        self.assertEqual(modal_description_heading, "Description")

        #check description text
        modal_description = self.browser.find_element(By.ID, 'modal-item-description').text
        self.assertEqual(modal_description, "This is item 2")        
        
        #check long description heading
        modal_long_details_heading = self.browser.find_element(By.ID, 'modal-item-details-heading').text
        self.assertEqual(modal_long_details_heading, "Details")
        
        #check long description text
        modal_item_long_description = self.browser.find_element(By.ID, 'modal-item-long-description').text
        self.assertEqual(modal_item_long_description, "A long description of item 2.")        
        
        ### Check image ###
        modal_image = self.browser.find_element(By.ID, 'modal-item-image')
        image_src = modal_image.get_attribute('src')
        
        # Ensure the image source is not empty (the image is loaded)
        self.assertTrue(image_src.endswith(self.items[1].picture.url))        
        
        # verify the qf code url is correct
        qr_code_element = self.browser.find_element(By.ID, 'modal-item-qrcode-img')
        qr_code_data = qr_code_element.get_attribute('src')
        base64_data = qr_code_data.split(',')[1]
        image_data = base64.b64decode(base64_data)
        image = Image.open(BytesIO(image_data))
        decoded_objects = decode(image)
        
        # Check the decoded contents
        for obj in decoded_objects:
          self.assertEqual(obj.data.decode('utf-8'), f'{self.live_server_url}/inventory/item/{self.items[1].id}/')

        if check_edit_button:
            #user is signed in so edit button should be visible
            edit_button = self.browser.find_element(By.ID, 'edit-btn')            
            self.assertTrue(edit_button.is_displayed(), "The edit button should be displayed")
        else:
            try:
                edit_button = self.browser.find_element(By.ID, 'edit-btn')
                self.fail("edit-btn is present, but it should not be.")
            except NoSuchElementException:
                # If NoSuchElementException is raised, the test passes
                pass    
          
    def test_modal_opens_and_doesnt_display_long_description(self, check_edit_button=False):
        # Navigate to the inventory page
        self.browser.get(f'{self.live_server_url}/inventory/')
        
        #wait for tile to load that doesn't have a long description
        item_element = WebDriverWait(self.browser, 20).until(
            EC.element_to_be_clickable((By.ID, f'item-{self.items[7].id}'))
        )
        
        item_element.click()
        
        # Wait for the modal to appear
        WebDriverWait(self.browser, 20).until(
            EC.visibility_of_element_located((By.ID, 'itemModal'))
        )
        
        # Wait until the title of the modal is populated (indicating the modal is fully loaded)
        WebDriverWait(self.browser, 20).until(
            lambda driver: driver.find_element(By.ID, 'modal-item-title').text != ''
        )        
        
        # the detail heading should not be visible
        details_heading = self.browser.find_element(By.ID, 'modal-item-details-heading')
        self.assertFalse(details_heading.is_displayed(), "The details heading should not be displayed")
          
        modal_item_long_description = self.browser.find_element(By.ID, 'modal-item-long-description')
        self.assertFalse(modal_item_long_description.is_displayed(), "The long description should not be displayed")
        
        if check_edit_button:
            #user is signed in so edit button should be visible
            edit_button = self.browser.find_element(By.ID, 'edit-btn')            
            self.assertTrue(edit_button.is_displayed(), "The edit button should be displayed")
        else:
            try:
                edit_button = self.browser.find_element(By.ID, 'edit-btn')
                self.fail("edit-btn is present, but it should not be.")
            except NoSuchElementException:
                # If NoSuchElementException is raised, the test passes
                pass                 

    def test_modal_close_by_clicking_x(self):
        # Navigate to the inventory page
        self.browser.get(f'{self.live_server_url}/inventory/')

        # Open the modal
        #wait for first tile to load
        item_element = WebDriverWait(self.browser, 20).until(
            EC.element_to_be_clickable((By.ID, f'item-{self.items[1].id}'))
        )
        item_element.click()

        # Wait for the modal to appear
        WebDriverWait(self.browser, 20).until(
            EC.visibility_of_element_located((By.ID, 'itemModal'))
        )
        
        # Wait until the title of the modal is populated (indicating the modal is fully loaded)
        WebDriverWait(self.browser, 20).until(
            lambda driver: driver.find_element(By.ID, 'modal-item-title').text != ''
        )        

        # Find and click the close button in the modal
        close_button = self.browser.find_element(By.CLASS_NAME, 'close')
        close_button.click()

        # Wait for the modal to be hidden
        WebDriverWait(self.browser, 20).until(
            EC.invisibility_of_element_located((By.ID, 'itemModal'))
        )

        # Assert that the modal is no longer visible
        modal = self.browser.find_element(By.ID, 'itemModal')
        self.assertFalse(modal.is_displayed())
        
    def test_modal_closes_by_clicking_off_modal(self):
        # Navigate to the inventory page
        self.browser.get(f'{self.live_server_url}/inventory/')

        # Open the modal
        #wait tile to load
        item_element = WebDriverWait(self.browser, 20).until(
            EC.element_to_be_clickable((By.ID, f'item-{self.items[5].id}'))
        )
        item_element.click()

        # Wait for the modal to appear
        WebDriverWait(self.browser, 20).until(
            EC.visibility_of_element_located((By.ID, 'itemModal'))
        )
        
        # Wait until the title of the modal is populated (indicating the modal is fully loaded)
        WebDriverWait(self.browser, 20).until(
            lambda driver: driver.find_element(By.ID, 'modal-item-title').text != ''
        )        

        #move the cursor to the far right of the modal plus 10 pixels
        modal = self.browser.find_element(By.ID, 'item-modal-content')
        ActionChains(self.browser).move_to_element_with_offset(modal, modal.size['width'] + 10, 0).click().perform()
        

        # Wait for the modal to be hidden
        WebDriverWait(self.browser, 20).until(
            EC.invisibility_of_element_located((By.ID, 'itemModal'))
        )

        # Assert that the modal is no longer visible
        modal = self.browser.find_element(By.ID, 'itemModal')
        self.assertFalse(modal.is_displayed())
        
    def test_search_filter(self):
        # Navigate to the inventory page
        self.browser.get(f'{self.live_server_url}/inventory/')
        
        #wait for first tile to load
        item_element = WebDriverWait(self.browser, 20).until(
            EC.element_to_be_clickable((By.ID, f'item-{self.items[1].id}'))
        )
        
        #search for 'Bedroom'
        search_input = self.browser.find_element(By.ID, 'search-input')
        search_input.send_keys('Bedroom')
        
        #hit search button
        search_button = self.browser.find_element(By.ID, 'search-button')
        search_button.click()
        
        # Wait for the search page to load (URL should contain keyword)
        WebDriverWait(self.browser, 20).until(
            EC.url_contains('keyword=Bedroom')
        )
        
        # Wait for filtered results to render
        WebDriverWait(self.browser, 20).until(
            EC.element_to_be_clickable((By.ID, f'item-{self.items[7].id}'))
        )
        
        #count the number of items displayed
        items = self.browser.find_elements(By.CSS_SELECTOR, "[id^='item-']")
        self.assertEqual(len(items), 7, "There should be 7 items displayed")
        
    def test_login_and_correct_redirection(self):
        # Navigate to the inventory page
        self.browser.get(f'{self.live_server_url}/inventory/')
        
        # Log in using shared helper
        login_from_page(self.browser, self.live_server_url)
        
        #ensure we are redirected to the inventory page
        WebDriverWait(self.browser, 20).until(
            EC.presence_of_element_located((By.ID, "feedback-button"))
        )
        
        #get current url
        self.assertEqual(self.browser.current_url, 
                         f'{self.live_server_url}/inventory/', 
                         "The user should be redirected to the inventory page after logging in")
        
    def test_login_and_home_button_brings_user_to_home_page(self):
      self.test_login_and_correct_redirection()
      self.test_home_button_brings_user_to_home_page()
        
    def test_login_and_all_inventory_items_are_displayed(self):
      self.test_login_and_correct_redirection()
      self.test_all_inventory_items_are_displayed()


    def test_login_and_modal_opens_and_displays_content_with_image(self):
      self.test_login_and_correct_redirection()
      self.test_modal_opens_and_displays_content_with_image(True)
      
    def test_login_and_modal_opens_and_doesnt_display_long_description(self):
      self.test_login_and_correct_redirection()
      self.test_modal_opens_and_doesnt_display_long_description(True)

    def test_login_and_modal_close_functionality(self):
      self.test_login_and_correct_redirection()
      self.test_modal_close_by_clicking_x()
        
    def test_login_and_modal_closes_by_clicking_off_modal(self):
      self.test_login_and_correct_redirection()
      self.test_modal_closes_by_clicking_off_modal()

    def test_login_and_search_filter(self):
      self.test_login_and_correct_redirection()
      self.test_search_filter()
      
@tag('selenium')
class ItemModalEditTests(StaticLiveServerTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.browser = webdriver.Chrome(options=get_chrome_options())
        cls.browser.set_window_size(1920, 1080)

    @classmethod
    def tearDownClass(cls):
        cls.browser.quit()
        super().tearDownClass()

    def setUp(self):
        # Reset browser state between tests
        self.browser.get('about:blank')
        self.browser.delete_all_cookies()

        # Create a white square placeholder image in memory
        image = Image.new('RGB', (100, 100), color='black')
        image_io = io.BytesIO()
        image.save(image_io, format='PNG')

        #create 12 items and assign them to an array called items
        self.items = []
        for i in range(1, 13):
            image_file = SimpleUploadedFile(f'test_image_{i}.png', image_io.getvalue(), content_type="image/png")
            
            if i <= 6:
              item = Item.objects.create(
                  name=f"Item {i}",
                  description=f"This is item {i}",
                  room="Living Room",
                  desc_long=f"A long description of item {i}.",
                  picture=image_file
              )
            else:
              item = Item.objects.create(
                  name=f"Item {i}",
                  description=f"This is item {i}",
                  room="Bedroom",
                  picture=image_file
              )
            
            self.items.append(item)
            
        self.test_user = User.objects.create_user(username='testuser', password='testpassword', is_staff=True)            
            
    def tearDown(self):
        # Clean up the test image files
        for item in self.items:
            item.picture.delete()
            
    def test_login_and_correct_redirection(self):
        # Navigate to the inventory page
        self.browser.get(f'{self.live_server_url}/inventory/')
        
        # Log in using shared helper
        login_from_page(self.browser, self.live_server_url)
        
        #ensure we are redirected to the inventory page
        WebDriverWait(self.browser, 20).until(
            EC.presence_of_element_located((By.ID, "feedback-button"))
        )
        
        #get current url
        self.assertEqual(self.browser.current_url, 
                         f'{self.live_server_url}/inventory/', 
                         "The user should be redirected to the inventory page after logging in")            
          
    #ensure edit button makes fields editable
    def test_modal_edit_button_with_long_description(self):
        # Navigate to the inventory page
        self.test_login_and_correct_redirection()
        
        item_element = WebDriverWait(self.browser, 20).until(
            EC.element_to_be_clickable((By.ID, f'item-{self.items[1].id}'))
        )
        item_element.click()

        # Wait for the modal to appear
        WebDriverWait(self.browser, 20).until(
            EC.visibility_of_element_located((By.ID, 'itemModal'))
        )
        
        # Wait until the title of the modal is populated (indicating the modal is fully loaded)
        WebDriverWait(self.browser, 20).until(
            lambda driver: driver.find_element(By.ID, 'modal-item-title').text != ''
        )        
        
        #hit the edit button
        edit_button = self.browser.find_element(By.ID, 'edit-btn')
        edit_button.click()
        
        #ensure the various fields are editable
        # Now check that the fields have been converted to editable input fields
        room_input = self.browser.find_element(By.ID, 'edit-room')
        description_textarea = self.browser.find_element(By.ID, 'edit-description')
        long_description_textarea = self.browser.find_element(By.ID, 'edit-long-description')

        # Verify that the elements are input and textarea fields
        self.assertEqual(room_input.tag_name, 'input', "Room field is not an input element.")
        self.assertEqual(description_textarea.tag_name, 'textarea', "Description field is not a textarea element.")
        self.assertEqual(long_description_textarea.tag_name, 'textarea', "Long description field is not a textarea element.")
        
        
    # the long description is not displayed but in edit mode it should be.  by added text to the long description field
    # it should then be visibile in the view modal
    def test_modal_edit_button_without_long_description(self):
        # Navigate to the inventory page
        self.test_login_and_correct_redirection()
        
        item_element = WebDriverWait(self.browser, 20).until(
            EC.element_to_be_clickable((By.ID, f'item-{self.items[7].id}'))
        )
        item_element.click()

        # Wait for the modal to appear
        WebDriverWait(self.browser, 20).until(
            EC.visibility_of_element_located((By.ID, 'itemModal'))
        )
        
        # Wait until the title of the modal is populated (indicating the modal is fully loaded)
        WebDriverWait(self.browser, 20).until(
            lambda driver: driver.find_element(By.ID, 'modal-item-title').text != ''
        )        
        
        #ensure the long description and details heading is not present in the view modal
        details_heading = self.browser.find_element(By.ID, 'modal-item-details-heading')
        self.assertFalse(details_heading.is_displayed(), "The details heading should not be displayed")
          
        modal_item_long_description = self.browser.find_element(By.ID, 'modal-item-long-description')
        self.assertFalse(modal_item_long_description.is_displayed(), "The long description should not be displayed")        
        
        #hit the edit button
        edit_button = self.browser.find_element(By.ID, 'edit-btn')
        edit_button.click()
        
        #modify the long description field
        long_description_textarea = self.browser.find_element(By.ID, 'edit-long-description')
        long_description_textarea.send_keys("This is a long description")
        
        #save the changes
        save_button = self.browser.find_element(By.ID, 'save-btn')
        save_button.click()
        
        #wait for the edit button to appear again
        WebDriverWait(self.browser, 20).until(
            EC.element_to_be_clickable((By.ID, 'edit-btn'))
        )
        
        #ensure the long description and details heading is present in the view modal and the description is correct
        details_heading = self.browser.find_element(By.ID, 'modal-item-details-heading')
        self.assertTrue(details_heading.is_displayed(), "The details heading should be displayed")
        
        modal_item_long_description = self.browser.find_element(By.ID, 'modal-item-long-description')
        self.assertTrue(modal_item_long_description.is_displayed(), "The long description should be displayed")
        self.assertEqual(modal_item_long_description.text, "This is a long description")
        
        #close the modal
        close_button = self.browser.find_element(By.CLASS_NAME, 'close')
        close_button.click()
        
        #wait for the modal to close
        WebDriverWait(self.browser, 20).until(
            EC.invisibility_of_element_located((By.ID, 'itemModal'))
        )
        
        #open the modal again so we can check the long description is still present
        item_element.click()
        
        # Wait for the modal to appear
        WebDriverWait(self.browser, 20).until(
            EC.visibility_of_element_located((By.ID, 'itemModal'))
        )
        
        # Wait until the title of the modal is populated (indicating the modal is fully loaded)
        WebDriverWait(self.browser, 20).until(
            lambda driver: driver.find_element(By.ID, 'modal-item-title').text != ''
        )        
        
        #save screenshot
        #self.browser.save_screenshot('modal.png')
        
        #ensure the long description and details heading is present in the view modal and the description is correct
        details_heading = self.browser.find_element(By.ID, 'modal-item-details-heading')
        self.assertTrue(details_heading.is_displayed(), "The details heading should be displayed")
        
        modal_item_long_description = self.browser.find_element(By.ID, 'modal-item-long-description')
        self.assertTrue(modal_item_long_description.is_displayed(), "The long description should be displayed")
        self.assertEqual(modal_item_long_description.text, "This is a long description")            


#TODO: add feedback tests
